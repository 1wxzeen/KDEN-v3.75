"""S4 launch, resume, pause and release verification. No outer score command."""
from pathlib import Path
import argparse, contextlib, datetime, json, os, sys
ROOT = Path(__file__).resolve().parent
DEFAULT_E = Path(os.environ.get('R14_EXPERIMENT_ROOT', str(ROOT.parents[1])))
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('command', choices=['menu', 'validate', 'run', 'status', 'pause', 'validate-run'])
p.add_argument('--experiment-root', type=Path, default=DEFAULT_E)
p.add_argument('--project-root', type=Path)
p.add_argument('--run-dir', type=Path)
p.add_argument('--max-new-units', type=int)
p.add_argument('--deep', action='store_true', help='Explicitly reread all inner predictions; slow and optional')
args = p.parse_args(); E = args.experiment_root.resolve(); R = args.project_root or E.parents[2]
sys.path[:0] = [str(E / 'src'), str(E / 'implementations/s3_v1')]
import engine, s0

class Tee:
    def __init__(self, original, log): self.original = original; self.log = log
    def write(self, data): self.original.write(data); self.log.write(data); self.log.flush()
    def flush(self): self.original.flush(); self.log.flush()

def execute(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'console.log').open('a', buffering=1) as log:
        with contextlib.redirect_stdout(Tee(sys.stdout, log)), contextlib.redirect_stderr(Tee(sys.stderr, log)):
            return engine.run(ROOT, E, R, directory, args.max_new_units)

def status(directory):
    record = s0.read_json(directory / 'status.json')
    try: os.kill(record['pid'], 0); alive = True
    except ProcessLookupError: alive = False
    except PermissionError: alive = None
    record['pid_exists_now'] = alive
    record['liveness_note'] = 'A PID can be reused; a running state plus an old timestamp is not proof of progress. Resume uses an exclusive OS lock.'
    return record

def menu():
    print('\nS4: tune AnEn and GAM, then freeze forecasts.\n')
    print('1  Start a new full run\n2  Resume a run\n3  Show status\n4  Request a pause after the current checkpoint\n5  Check the installed implementation\n0  Exit')
    choice = input('\nChoose a number: ').strip()
    if choice == '0': return {'status': 'EXIT'}
    if choice == '5': engine.binding(ROOT, E, R); return {'status': 'VALID_IMPLEMENTATION'}
    if choice == '1':
        directory = E / 'runs' / ('r14-s4-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        print('Run folder:', directory, '\nKeep this terminal open. Ctrl+C requests a pause after the current checkpoint.\n')
        return execute(directory)
    s0.require(choice in ['2', '3', '4'], 'Choose a listed option')
    runs = sorted((E / 'runs').glob('r14-s4-*'), reverse=True)
    s0.require(runs, 'No S4 run folders yet')
    for i, directory in enumerate(runs, 1):
        state = s0.read_json(directory / 'status.json').get('state') if (directory / 'status.json').exists() else 'not started'
        print(f'{i}  {directory.name}  [{state}]')
    number = int(input('Run number: ')); s0.require(1 <= number <= len(runs), 'Invalid run number')
    directory = runs[number-1]
    if choice == '3': return status(directory)
    if choice == '4': (directory / 'PAUSE').touch(); return {'status': 'PAUSE_REQUESTED', 'note': 'Current checkpoint finishes first.'}
    (directory / 'PAUSE').unlink(missing_ok=True)
    return execute(directory)

try:
    s0.require(args.max_new_units is None or args.max_new_units > 0, '--max-new-units must be positive')
    if args.command == 'menu': result = menu()
    elif args.command == 'validate': engine.binding(ROOT, E, R); result = {'status': 'VALID_IMPLEMENTATION'}
    else:
        s0.require(args.run_dir is not None, '--run-dir is required')
        directory = args.run_dir.resolve()
        if args.command == 'run': result = execute(directory)
        elif args.command == 'status': result = status(directory)
        elif args.command == 'pause':
            s0.require(directory.is_dir(), 'Unknown run'); (directory / 'PAUSE').touch(); result = {'status': 'PAUSE_REQUESTED'}
        else: result = engine.validate_run(ROOT, E, R, directory, args.deep)
    print(json.dumps(result, indent=2, sort_keys=True))
except Exception as exc:
    print(json.dumps({'status': 'FAILED', 'error': str(exc)}), file=sys.stderr); sys.exit(1)
