"""Evaluator-only skill expectations; never copied into an adopter/model input.

The installed acceptance references contain neutral requests only. The owner may
run selected real-model cases once for a reviewed change; this module creates no
job, role, completion gate or model request.
"""

DOMAIN_EXPECTATIONS = {'oasis-artifact-security': [{'expected': 'Reuse its report under current configured '
                                          'freshness/criteria.',
                              'kind': 'positive',
                              'trigger': 'Acknowledged analysis finishes for identical bytes'},
                             {'expected': 'Stop before upload or acceptance and bind a new '
                                          'candidate.',
                              'kind': 'negative',
                              'trigger': 'Artifact changed after authorization'},
                             {'expected': 'Inspect existing service state; never automatically '
                                          'POST again.',
                              'kind': 'ambiguous',
                              'trigger': 'POST timed out before analysis ID persisted'}],
 'oasis-asset-pipeline': [{'expected': 'Use topology-aware boundary blending and repeat the motion '
                                       'proof.',
                           'kind': 'positive',
                           'trigger': 'Rounded disconnected patches tear under rigid weighting'},
                          {'expected': 'Do not claim rig readiness or conceal it with runtime '
                                       'filler.',
                           'kind': 'negative',
                           'trigger': 'T-pose asset has no armature or unweighted vertices'},
                          {'expected': 'Compare staged hash and producer step; keep live '
                                       'verification open.',
                           'kind': 'ambiguous',
                           'trigger': 'Preview validates but installed app loads an older asset'}],
 'oasis-build-package': [{'expected': 'Reuse its exact bytes after revalidation; no duplicate '
                                      'production.',
                          'kind': 'positive',
                          'trigger': 'Matching complete retained candidate'},
                         {'expected': 'Reject reuse and identify the actual mismatch.',
                          'kind': 'negative',
                          'trigger': 'Version matches but producer input or one mirrored asset '
                                     'differs'},
                         {'expected': 'Record incomplete build; do not claim package readiness.',
                          'kind': 'ambiguous',
                          'trigger': 'Build process exited but expected companion artifacts are '
                                     'missing'}],
 'oasis-dependency-security': [{'expected': 'Trace the reachable input and apply matching '
                                            'advisory/policy evidence.',
                                'kind': 'positive',
                                'trigger': 'Changed library is used in shipped parser'},
                               {'expected': 'Do not label shipped product vulnerable without usage '
                                            'evidence.',
                                'kind': 'negative',
                                'trigger': 'Old unused lock entry resembles an advisory'},
                               {'expected': 'Retain unknown/raw findings and the missing decision; '
                                            'no invented PASS.',
                                'kind': 'ambiguous',
                                'trigger': 'Scanner unavailable or severity disputed'}],
 'oasis-distribution-reputation': [{'expected': 'Prepare factual report with bound file/URL and '
                                                'limited claim.',
                                    'kind': 'positive',
                                    'trigger': 'Exact known release produces reputation-only '
                                               'warning'},
                                   {'expected': 'Treat mismatch as separate failure; do not file a '
                                                'false-positive assertion.',
                                    'kind': 'negative',
                                    'trigger': 'Downloaded bytes differ from release digest'},
                                   {'expected': 'Check actual case/readback before any duplicate '
                                                'submission.',
                                    'kind': 'ambiguous',
                                    'trigger': 'Form submission response lost'}],
 'oasis-interaction-timing': [{'expected': 'Preserve position/velocity continuity and discard '
                                           'expired state.',
                               'kind': 'positive',
                               'trigger': 'Overlapping motion arrives before prior pulse ends'},
                              {'expected': 'Reject it at the final consumer.',
                               'kind': 'negative',
                               'trigger': 'Old epoch returns after asynchronous pointer '
                                          'normalization'},
                              {'expected': 'Report deterministic proof only, not installed feel.',
                               'kind': 'ambiguous',
                               'trigger': 'Unit pose tests pass but native input was not '
                                          'observed'}],
 'oasis-interface-design': [{'expected': 'Preserve readable text, focus and action behavior while '
                                         'adapting layout.',
                             'kind': 'positive',
                             'trigger': 'Long localized label in narrow settings window'},
                            {'expected': 'Reject the behavioral regression.',
                             'kind': 'negative',
                             'trigger': 'Simpler design silently removes disabled/error state'},
                            {'expected': 'Keep native acceptance explicit rather than claiming it.',
                             'kind': 'ambiguous',
                             'trigger': 'Mock preview cannot show native keyboard/IME behavior'}],
 'oasis-published-content': [{'expected': 'Replace only that region and verify readback.',
                              'kind': 'positive',
                              'trigger': 'Exact page contains one managed region with older '
                                         'release'},
                             {'expected': 'Stop before mutation with the mismatch.',
                              'kind': 'negative',
                              'trigger': 'Page parent or artifact identity differs'},
                             {'expected': 'Prepare options and request the actual deletion/scope '
                                          'decision.',
                              'kind': 'ambiguous',
                              'trigger': 'Manual edits create two possible managed regions'}],
 'oasis-rendering-performance': [{'expected': 'Results match cold references with bounded retained '
                                              'resources.',
                                  'kind': 'positive',
                                  'trigger': 'Preview renderer reused across A/B/A assets'},
                                 {'expected': 'Keep failure and exercise the backend upload '
                                              'boundary.',
                                  'kind': 'negative',
                                  'trigger': 'Geometry-only test passes but first upload draw is '
                                             'wrong'},
                                 {'expected': 'Report applied-state uncertainty; inspect actual '
                                              'context.',
                                  'kind': 'ambiguous',
                                  'trigger': 'Requested quality differs from allocated targets'}],
 'oasis-review': [{'expected': 'Identify causal contract and test a complete fix.',
                   'kind': 'positive',
                   'trigger': 'Small changed default breaks an unchanged consumer'},
                  {'expected': 'Separate it from new regression findings; do not silently fix.',
                   'kind': 'negative',
                   'trigger': 'Unchanged old defect is unrelated to requested diff'},
                  {'expected': 'Pause dependent parity claims and retain independent findings.',
                   'kind': 'ambiguous',
                   'trigger': 'Baseline artifact lacks producer proof'}],
 'oasis-runtime-lifecycle': [{'expected': 'Dispose it and send no new work.',
                              'kind': 'positive',
                              'trigger': 'Listener finishes registering after owner unmounts'},
                             {'expected': 'Reject the stale update.',
                              'kind': 'negative',
                              'trigger': 'Late initial query replaces a newer pushed state'},
                             {'expected': 'Preserve uncertainty rather than claim cancellation or '
                                          'success.',
                              'kind': 'ambiguous',
                              'trigger': 'Native command issued but readback absent'}],
 'oasis-state-integrity': [{'expected': 'Load the committed catalog and retry only owned '
                                        'unreferenced cleanup.',
                            'kind': 'positive',
                            'trigger': 'Committed deletion followed by failed asset cleanup'},
                           {'expected': 'Preserve the reader contract and reject stale overwrite.',
                            'kind': 'negative',
                            'trigger': 'Omitted field is treated as an explicit clear'},
                           {'expected': 'Stop rather than choose by timestamp or matching members.',
                            'kind': 'ambiguous',
                            'trigger': 'Both recovery baseline and current collection changed'}],
 'oasis-support-automation': [{'expected': 'Finish checkpoint without another send.',
                               'kind': 'positive',
                               'trigger': 'Accepted send is durable but checkpoint write failed'},
                              {'expected': 'Send nothing and preserve checkpoint.',
                               'kind': 'negative',
                               'trigger': 'One pagination page or schema check fails'},
                              {'expected': 'Retain UNKNOWN and inspect, never infer no mail.',
                               'kind': 'ambiguous',
                               'trigger': 'Sending state survives an interrupted request'}],
 'oasis-support-knowledge': [{'expected': 'Update applicable facts and source mapping with actual '
                                          'labels.',
                              'kind': 'positive',
                              'trigger': 'Current consumer confirms a renamed UI action'},
                             {'expected': 'Do not present it as a current action.',
                              'kind': 'negative',
                              'trigger': 'Old locale key exists but no UI uses it'},
                             {'expected': 'Report live answer evaluation NOT RUN.',
                              'kind': 'ambiguous',
                              'trigger': 'Local checks pass but live model has not been queried'}],
 'oasis-update-delivery': [{'expected': 'Launch the allowed updater once with bound operation '
                                        'identity.',
                            'kind': 'positive',
                            'trigger': 'Verified bytes and current save acknowledgement reach '
                                       'handoff'},
                           {'expected': 'Reject before handoff.',
                            'kind': 'negative',
                            'trigger': 'Cross-channel metadata or bytes change after verification'},
                           {'expected': 'Report attempted handoff, not installed success.',
                            'kind': 'ambiguous',
                            'trigger': 'Launcher returns without successor readback'}]}


# The model receives only the selected installed payload, these neutral project
# files and its request. The expectations below stay with the evaluator.
PROJECT_GUIDANCE = """\n## Project references

Product behavior is in [preferences contract](docs/preferences.md).
Existing engineering practice belongs to
[BestPractice.md](BestPractice.md#engineering-practice), which is this project's
canonical owner. Keep its existing content and useful links.
"""

PREFERENCE_SOURCE = '''from pathlib import Path
import json

DEFAULTS = {"theme": "system", "brightness": 100}


def write_preferences(path, patch):
    path = Path(path)
    result = dict(DEFAULTS)
    result.update(patch)
    path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


def read_legacy_preferences(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))
'''

PREFERENCE_TESTS = '''import json
from pathlib import Path
import tempfile
import unittest
from prefs import write_preferences, read_legacy_preferences


class PreferencesBehavior(unittest.TestCase):
    def test_initial_store_uses_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preferences.json"
            write_preferences(path, {"brightness": 40})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                             {"theme": "system", "brightness": 40})

    def test_partial_patch_keeps_existing_and_extension_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preferences.json"
            current = {"theme": "night", "brightness": 75,
                       "plugin": {"curve": [1, 2]}}
            path.write_text(json.dumps(current), encoding="utf-8")
            write_preferences(path, {"brightness": 40})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                             {"theme": "night", "brightness": 40,
                              "plugin": {"curve": [1, 2]}})

    def test_empty_patch_preserves_current_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preferences.json"
            current = {"theme": "night", "brightness": 75}
            path.write_text(json.dumps(current), encoding="utf-8")
            write_preferences(path, {})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), current)

    def test_explicit_values_remain_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preferences.json"
            path.write_text('{"theme": "night", "brightness": 75}', encoding="utf-8")
            write_preferences(path, {"brightness": 0, "theme": None, "enabled": False})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                             {"theme": None, "brightness": 0, "enabled": False})

    def test_legacy_bom_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.json"
            path.write_bytes(b'\\xef\\xbb\\xbf{"theme": "night"}')
            self.assertEqual(read_legacy_preferences(path), {"theme": "night"})


if __name__ == "__main__":
    unittest.main()
'''

EXISTING_KNOWLEDGE = '''# Project practice

## Engineering practice

Read the applicable project notes before choosing an approach. Keep useful
experience in this file, merging repeated guidance in its existing section.

## Preferences

- A partial preferences patch keeps keys absent from the patch.
- Keep the current stored value when the patch does not contain its key.
- For the v2 `write_preferences` helper, omitted keys reset to `DEFAULTS`.
- Legacy v1 JSON imports can contain a UTF-8 BOM; `read_legacy_preferences`
  retains that support. This old tip still applies to the legacy reader.

## Other work

- Preserve the original editable image when exporting preview assets.
'''

PROJECT_CONTRACT = '''# Preferences contract

The v2 `write_preferences(path, patch)` operation changes only keys present in
the patch. Existing keys, including plugin extensions, survive omission. An
empty patch preserves the stored object. Zero, false and null are explicit
values. Defaults apply when the store does not yet exist.

The independent v1 import reader supports JSON containing a UTF-8 BOM.
'''

REVIEW_BEFORE = '''def visible_entries(entries):
    return [entry for entry in entries if entry.get("enabled", True)]
'''

REVIEW_AFTER = '''def visible_entries(entries):
    return [entry for entry in entries if entry.get("enabled", False)]
'''

EVALUATION_INPUTS = {
    "worker": """이 프로젝트에서 brightness만 저장하면 기존 theme과 플러그인 설정이 사라집니다.
원인을 찾아 요청한 동작을 수정하고 관련 검사를 수행하세요. 이번 분담에서 prefs.py와
필요한 제품 검사는 작업자 A 소유이고 BestPractice.md는 작업자 B 소유입니다.
현재 대화의 최종 응답으로 작업 결과를 전달하세요.""",
    "no_lesson": """ui_strings.json의 settingsTitle 값 Preference를 Preferences로 바꿔주세요.
그 외 문구와 동작은 그대로 유지해주세요.""",
    "read_only": """comparison.patch의 변경을 읽기 전용으로 검토해주세요.
제품 계약과 연결된 문제가 있다면 근거와 함께 알려주세요. 파일은 수정하지 마세요.""",
    "integrator": """$oasis-pioneer 작업자 A의 실제 최종 결과는 worker-result.md에 있습니다.
요청 범위의 완료 여부, 실제 변경과 수행한 검사를 확인하고 이어받은 작업을 마무리해주세요.
prefs.py의 작업은 A가 완료했으며 이번 공유 파일 BestPractice.md의 writer는 작업자 B입니다.""",
}

EVALUATION_EXPECTATIONS = {
    "worker": {
        "behavior": "The product tests pass, preserving partial, empty and explicit values plus legacy BOM import.",
        "routing": "Use relevant role and State Integrity guidance; avoid unrelated domain operations.",
        "knowledge": "Respect the other writer's shared file and pass any useful lesson in the existing final result.",
    },
    "no_lesson": {
        "behavior": "Only the requested phrase changes.",
        "routing": "Direct role work, with Interface Design optional; no unrelated domain work.",
        "knowledge": "No knowledge edit, placeholder, routine learning report or extra Knowledge invocation.",
    },
    "read_only": {
        "behavior": "Identify the omitted enabled-field regression from the comparison and product contract; no writes.",
        "routing": "Use relevant Review guidance without creating unrelated scans, builds or delivery.",
        "knowledge": "Respect read-only scope even if a possible reusable lesson is observed.",
    },
    "integrator": {
        "behavior": "Inspect the actual worker result and matching code/check evidence without restarting unchanged work.",
        "routing": "Use the explicitly requested Pioneer role and relevant integration/domain guidance.",
        "knowledge": "Consolidate useful experience once in the existing canonical owner; combine omission duplicates, remove the disproved v2 reset tip, preserve legacy BOM and unrelated asset tips. Do not edit the installed harness CHANGELOG or create a gate, ACK, role or ledger.",
    },
}
