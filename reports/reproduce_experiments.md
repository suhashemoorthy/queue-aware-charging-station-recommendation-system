# Reproducing the Algorithm Comparison

Run commands from the `backend/` directory.

## Requirements

Use the project's Python 3.11 virtual environment and install its pinned dependencies. PDF generation additionally uses ReportLab:

```bash
source .venv311/bin/activate
uv pip install -r requirements.txt
uv pip install reportlab
```

## Run

```bash
python -m eval.generate_research_report --trials 300 --users 12 --seed 7
```

The generator runs the existing paired simulation for low, medium, and high demand. It records the data SHA-256, seed, parameters, machine/software information, candidate-generation timing, picker timing, scenario wall time, and process peak RSS. Completed demand levels are checkpointed under `reports/`; rerunning the same command resumes compatible completed levels. Use `--fresh` to ignore a previous checkpoint. Optional parameters are `--trials`, `--users`, and `--seed`.

## Interpretation

The dataset is synthetic station data, not business entities. No entity matching labels exist, so precision, recall, F1/F0.5, TP/FP/FN, and candidate recall are unavailable. Scenario trip outcomes are simulated; runtime figures are local measurements on the recorded machine. Runtime timing is descriptive, and no compute-time significance test is performed. Do not compare these simulated travel/charge minutes to field observations.
