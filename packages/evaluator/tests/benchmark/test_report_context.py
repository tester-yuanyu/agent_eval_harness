from eval_framework.benchmark.report_context import scope_evidence, scope_html


def test_scope_counts_only_selected_tasks_and_explicit_scored_metrics():
    run = {'planned_case_ids': ['a', 'b'], 'trials_per_case': 2, 'trials': [
        {'case_id': 'a', 'trial': 1, 'assessment': {'metrics': [
            {'name': 'x', 'formal': True, 'status': 'SCORED'},
            {'name': 'x', 'formal': True, 'status': 'SCORED'},
            {'name': 'aux', 'formal': False, 'status': 'SCORED'},
            {'name': 'pending', 'formal': True, 'status': 'ERROR'},
            {'name': 'legacy', 'status': 'SCORED'}]}},
        {'case_id': 'a', 'trial': 2, 'assessment': {'metrics': []}}]}
    tasks = {'a': {'coverage_tags': ['safety', 'safety']}, 'b': {'coverage_tags': ['missing']}, 'unused': {'coverage_tags': ['extra']}}
    scope = scope_evidence(run, tasks)
    assert scope['tags'] == {'missing': {'planned': 1, 'executed': 0}, 'safety': {'planned': 1, 'executed': 1}}
    assert scope['metrics'] == {'pending': {'recorded': 1, 'scored': 0}, 'x': {'recorded': 1, 'scored': 1}}
    assert scope['unmarked_metrics'] == 1


def test_scope_html_escapes_metadata_and_does_not_invent_baseline():
    run = {'planned_case_ids': ['a'], 'trials': [], 'trials_per_case': 1}
    html = scope_html(run, {'a': {'coverage_tags': ['<img src=x>']}})
    assert '&lt;img src=x&gt;' in html and '<img src=x>' not in html
    assert '未载入并验证对照运行' in html
    assert '不等于通过' in html
    assert '安全认证' in html
