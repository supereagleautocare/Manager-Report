"""The user's 11/11 example is a benchmark, never a source for actuals."""


def comparison(view):
    if view['source']['as_of'] != '2026-11-11':
        return None
    rows = []
    expected = {'Robert':(17.6,20), 'Mike':(42.4,40), 'Ryan':(35.05,40),
                'Vegas':(26.6,40), 'Juan':(17.85,40), 'Justin':(29.15,40)}
    for row in view['techs']:
        if row['label'] in expected:
            value,goal=expected[row['label']]
            rows.append(dict(label=row['label']+' hours pace',kind='hours',reference=value,calculated=row['pace'],reference_goal=goal,goal=row['goal']))
    for row in view['advisors']:
        first=row['label'].split()[0]
        if first in ('Enoch','Morgan'):
            rows.append(dict(label=first+' GP pace',kind='money',reference=13601 if first=='Enoch' else 13145,
                             calculated=row['pace'],reference_goal=16500,goal=row['goal']))
    for row,value,goal in zip(view['gp_rows'],[91553,24092,4818],[125400,33000,6600]):
        rows.append(dict(label=row['label'],kind='money',reference=value,calculated=row['pace'] if row['pace'] is not None else row['actual'],reference_goal=goal,goal=row['goal']))
    expected_kpis={'Average repair order':(477,600),'Average quote':(1409,1200),
                   'GP per billed hour':(141,150),'Cars posted':(323,440)}
    for row in view['kpis']:
        if row['label'] in expected_kpis:
            value,goal=expected_kpis[row['label']]
            rows.append(dict(label=row['label'],kind=row['kind'],reference=value,
                             calculated=row['pace'] if row['pace'] is not None else row['actual'],reference_goal=goal,goal=row['goal']))
    for row in rows:
        row['difference']=row['calculated']-row['reference'] if row['calculated'] is not None else None
    return dict(rows=rows,notes=[
        'The reference’s six technician rows add to 168.65 hours; its printed total is 169.20.',
        'The reference’s two advisor rows add to $26,746; its printed total is $26,620.',
        'Dashboard totals always sum the underlying rows; they do not copy inconsistent printed totals.',
        'Calculated values read today’s synced records for November 11. Historical workbook records and Tekmetric tickets may have been revised. Differences remain visible; reference actuals are never substituted.'
    ])
