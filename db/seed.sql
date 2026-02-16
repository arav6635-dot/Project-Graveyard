-- Project Graveyard seed data (DB-native, no hardcoded Python sample objects)

INSERT OR IGNORE INTO projects(
  title, summary, category, status,
  idea_origin, problem_target, target_audience,
  stack, team_size, duration_months, budget_range,
  timeline, what_happened, why_failed, lessons_learned,
  burnout_level, market_signal, tech_debt_level, created_at
) VALUES
(
  'Async Journal AI',
  'Voice journaling app that auto-generated weekly mood reports.',
  'Productivity',
  'Archived',
  'Personal pain point',
  'Inconsistent self-reflection',
  'Solo professionals',
  'FastAPI, React Native, Whisper',
  1,
  5,
  '$500-$2k',
  'MVP done in month 2, plateaued by month 5',
  'Retention dropped below 8% and acquisition was too expensive.',
  'No strong habit loop; value appeared only after 2 weeks.',
  'Design value in first session and focus on one persona.',
  7,
  3,
  4,
  datetime('now')
),
(
  'Indie API Marketplace',
  'Marketplace for developers to list niche APIs.',
  'Developer Tools',
  'Abandoned',
  'Twitter trend',
  'Discoverability for indie APIs',
  'Indie hackers',
  'Django, PostgreSQL, Stripe',
  2,
  8,
  '$2k-$10k',
  'Built many features before validating supply side',
  'Too few quality APIs listed; buyers found poor coverage.',
  'Cold-start problem with no wedge strategy.',
  'Constrain supply first, then grow demand vertically.',
  6,
  4,
  6,
  datetime('now')
);

INSERT OR IGNORE INTO project_cause_votes(project_id, cause_id, votes, source)
SELECT p.id, c.id, 1, 'seed'
FROM projects p
JOIN failure_causes c ON c.name = 'No Market Need'
WHERE p.title = 'Async Journal AI';

INSERT OR IGNORE INTO project_cause_votes(project_id, cause_id, votes, source)
SELECT p.id, c.id, 1, 'seed'
FROM projects p
JOIN failure_causes c ON c.name = 'Poor Distribution'
WHERE p.title = 'Async Journal AI';

INSERT OR IGNORE INTO project_cause_votes(project_id, cause_id, votes, source)
SELECT p.id, c.id, 1, 'seed'
FROM projects p
JOIN failure_causes c ON c.name = 'Lost Motivation'
WHERE p.title = 'Async Journal AI';

INSERT OR IGNORE INTO project_cause_votes(project_id, cause_id, votes, source)
SELECT p.id, c.id, 1, 'seed'
FROM projects p
JOIN failure_causes c ON c.name = 'Scope Creep'
WHERE p.title = 'Indie API Marketplace';

INSERT OR IGNORE INTO project_cause_votes(project_id, cause_id, votes, source)
SELECT p.id, c.id, 1, 'seed'
FROM projects p
JOIN failure_causes c ON c.name = 'No Monetization Path'
WHERE p.title = 'Indie API Marketplace';

INSERT OR IGNORE INTO project_cause_votes(project_id, cause_id, votes, source)
SELECT p.id, c.id, 1, 'seed'
FROM projects p
JOIN failure_causes c ON c.name = 'Technical Complexity'
WHERE p.title = 'Indie API Marketplace';
