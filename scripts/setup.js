const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const venv = path.join(root, '.venv');
const py = process.platform === 'win32'
  ? path.join(venv, 'Scripts', 'python.exe')
  : path.join(venv, 'bin', 'python');

if (!fs.existsSync(venv)) {
  console.log('Creating .venv…');
  const r = spawnSync('python', ['-m', 'venv', venv], { stdio: 'inherit', cwd: root });
  if (r.status !== 0) process.exit(r.status || 1);
}

console.log('Installing backend dependencies…');
const pip = spawnSync(py, ['-m', 'pip', 'install', '-r', 'requirements.txt'], {
  stdio: 'inherit',
  cwd: path.join(root, 'backend'),
});
process.exit(pip.status || 0);