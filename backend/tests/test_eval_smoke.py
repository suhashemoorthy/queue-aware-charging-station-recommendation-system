from eval.compare_rankers import report, run


def test_comparison_harness_runs_and_reports():
    results = run(trials=2, users_per_trial=4, seed=1, load_name="medium")
    text = report("medium", results)
    assert "new_ranker (after)" in text and "legacy_ranker (before)" in text
    names, per_trial, totals, *_ = results
    assert all(len(per_trial[n]) == 2 for n in names)
    assert all(t > 0 for n in names for t in totals[n])
