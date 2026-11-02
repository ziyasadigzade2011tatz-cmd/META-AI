"""Read-only self-development assessment. Does not grant access to META Core."""
from pathlib import PurePosixPath

def self_assess(snapshot, edits):
    names=sorted(set(snapshot)|set(edits))
    candidates=[n for n in names if n.replace("\\","/").split("/")[-1] in ("engine.py","api.py","workspace.py","runner.py","web_tools.py","context.py")]
    return {
      "status":"assessment_only", "candidate_files":candidates[:30],
      "next_steps":["Read relevant project source", "Identify a concrete bug or measurable improvement", "Create changes in overlay", "Run approved tests", "Finish with a pending diff for human review"],
      "limitations":"This action cannot access D:/META/Core unless its files are included in the selected allowed workspace; never silently modify the installed Core.",
      "approval_required":True
    }
