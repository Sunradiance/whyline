const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const venv = path.join(root, '.venv');
const py = process.platform === 'win32'
  ? path.join(venv, 'Scripts', 'python.exe')
  : path.join(venv, 'bin', 'python');

if (!fs.existsSync(py)) {
  console.error('Run npm run setup first.');
  process.exit(1);
}

const child = spawn(py, [path.join(root, 'mcp', 'server.py')], {
  cwd: root,
  stdio: 'inherit',
  env: process.env,
});
child.on('exit', (code) => process.exit(code ?? 0));