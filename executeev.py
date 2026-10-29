from pathlib import Path
import shutil
import subprocess
import sys
import threading


ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
BACKEND_PYTHON = BACKEND / ".venv311" / "bin" / "python"


def main():
    if not BACKEND_PYTHON.is_file():
        print(
            "Backend environment not found. Create it with Python 3.11 first:\n"
            "  cd backend && uv venv --python 3.11 .venv311 && "
            "uv pip install --python .venv311/bin/python -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    npm = shutil.which("npm")
    if npm is None:
        print("npm was not found. Install Node.js and npm first.", file=sys.stderr)
        return 1

    if not (FRONTEND / "node_modules").is_dir():
        print("Installing frontend dependencies...")
        try:
            subprocess.run([npm, "install"], cwd=FRONTEND, check=True)
        except subprocess.CalledProcessError as error:
            return error.returncode

    commands = [
        (
            "Backend",
            [str(BACKEND_PYTHON), "-m", "uvicorn", "app.main:app", "--reload"],
            BACKEND,
        ),
        ("Frontend", [npm, "run", "dev"], FRONTEND),
    ]
    processes = []
    exited = threading.Event()

    def watch_process(process, name):
        code = process.wait()
        print(f"{name} stopped with exit code {code}.")
        exited.set()

    try:
        for name, command, cwd in commands:
            print(f"Starting {name}...")
            process = subprocess.Popen(command, cwd=cwd)
            processes.append(process)
            threading.Thread(
                target=watch_process, args=(process, name), daemon=True
            ).start()

        print("Both servers are running. Press Ctrl+C to stop them.")
        exited.wait()
    except KeyboardInterrupt:
        print("Stopping servers...")
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())