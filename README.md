# Queue-aware charging station recommendation system

An EV charging station recommendation app with queue-aware ranking, route and charging-time estimates, live-data integrations, and reservation/queue handling.

## Requirements

- Python 3.11
- Node.js and npm

## Run

From the project root, prepare the backend environment once:

```bash
cd backend
python3.11 -m venv .venv311
source .venv311/bin/activate
pip install -r requirements.txt
cd ..
```

Then start both services:

```bash
python3 executeev.py
```

The frontend is served at `http://localhost:5173`; the API documentation is at `http://localhost:8000/docs`. Press Ctrl+C to stop both services. The launcher installs frontend npm packages on its first run.

To configure optional live-data providers, copy `backend/.env.example` to `backend/.env` and fill in the values you have. Do not commit `backend/.env`.

## Tests

```bash
cd backend
.venv311/bin/python -m pytest -q
```

## Project documentation

- [Algorithm notes](docs/ALGORITHMS.md)
- [Technical description](docs/TECHNICAL_DESCRIPTION.md)