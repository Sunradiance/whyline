const { spawnSync } = require('child_process');
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

const r = spawnSync(py, ['-m', 'pytest', 'tests', '-q'], {
  stdio: 'inherit',
  cwd: root,
});
process.exit(r.status || 0);