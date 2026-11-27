import pytest

from zoha import skill_install as si

GOOD = "---\nname: Weekly Report\ndescription: Write a weekly status report\n---\n\n# Steps\nDo the thing.\n"


def test_github_blob_becomes_raw():
    assert si.raw_url("https://github.com/a/b/blob/main/x/y.md") == "https://raw.githubusercontent.com/a/b/main/x/y.md"
    assert si.raw_url("https://example.com/s.md") == "https://example.com/s.md"


def test_install_saves_slugged_file(tmp_path):
    p = si.install("https://example.com/s.md", fetch=lambda u: GOOD, skills_dir=tmp_path)
    assert p.name == "weekly-report.md" and p.read_text(encoding="utf-8") == GOOD
    assert si.list_skills(tmp_path) == [("weekly-report", "Write a weekly status report")]


def test_refuses_overwrite_unless_forced(tmp_path):
    si.install("https://x.test/s.md", fetch=lambda u: GOOD, skills_dir=tmp_path)
    with pytest.raises(si.SkillError):
        si.install("https://x.test/s.md", fetch=lambda u: GOOD, skills_dir=tmp_path)
    si.install("https://x.test/s.md", force=True, fetch=lambda u: GOOD, skills_dir=tmp_path)


def test_rejects_files_without_header(tmp_path):
    with pytest.raises(si.SkillError):
        si.install("https://x.test/s.md", fetch=lambda u: "# just notes", skills_dir=tmp_path)


def test_rejects_non_https_and_path_tricks(tmp_path):
    with pytest.raises(si.SkillError):
        si._fetch("http://x.test/s.md")
    evil = "---\nname: ../../evil\ndescription: x\n---\nbody"
    p = si.install("https://x.test/s.md", fetch=lambda u: evil, skills_dir=tmp_path)
    assert p.parent == tmp_path and p.name == "evil.md"
