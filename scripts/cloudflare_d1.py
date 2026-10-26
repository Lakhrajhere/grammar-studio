"""Use the existing Wrangler login; no API credentials are copied into the repo."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def wrangler_command():
    installed = shutil.which('wrangler')
    if installed:
        return [installed]
    node = shutil.which('node')
    cached = list((Path.home() / '.npm/_npx').glob('*/node_modules/wrangler/bin/wrangler.js'))
    if node and cached:
        newest = max(cached, key=lambda path: path.stat().st_mtime)
        return [node, str(newest)]
    raise RuntimeError('Wrangler is unavailable. Run npx wrangler login first.')


def parse_results(output):
    # File imports can print upload progress before the JSON response.
    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character != '[':
            continue
        try:
            result, _ = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(result, list) and result and all(isinstance(item, dict) and item.get('success') is True for item in result):
            return result
    raise RuntimeError('Cloudflare did not return a successful JSON result.')


def execute(database, *, command=None, sql_file=None):
    if (command is None) == (sql_file is None):
        raise ValueError('Provide one SQL command or SQL file.')
    args = wrangler_command() + ['d1', 'execute', database, '--remote', '--json']
    args += ['--command', command] if command is not None else ['--file', str(sql_file)]
    environment = dict(os.environ, WRANGLER_SEND_METRICS='false',
                       WRANGLER_LOG_PATH=str(Path(tempfile.gettempdir()) / 'grammar-wrangler-logs'))
    result = subprocess.run(args, text=True, capture_output=True, env=environment)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Cloudflare request failed.')
    return parse_results(result.stdout)


def query(database, sql):
    return [row for result in execute(database, command=sql) for row in result.get('results', [])]
