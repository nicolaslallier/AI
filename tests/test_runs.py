from common.runs import new_run_dir


def test_new_run_dir_never_reuses_a_directory(tmp_path):
    a = new_run_dir("exp", tmp_path)
    (a / "adapters").mkdir()
    b = new_run_dir("exp", tmp_path)
    c = new_run_dir("exp", tmp_path)
    assert len({a, b, c}) == 3
    assert b.name == f"{a.name}-2" and c.name == f"{a.name}-3"
    assert (a / "adapters").is_dir()
