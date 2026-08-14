# Mahogany Hub

## Purpose

Unattended landing + Telegram + Instagram content hub for Mahogany, Calgary.

## Requirements

### Requirement: Landing funnel

The system SHALL serve a static SEO landing page that links to Telegram `@mahogany_calgary` and displays refreshed community/market stats.

#### Scenario: Visitor joins Telegram

- **WHEN** a visitor opens the landing CTA
- **THEN** they are directed to `t.me/mahogany_calgary`

### Requirement: Telegram scheduled posting

The system SHALL post automated content to configured forum thread IDs for news, real estate, rentals, deals, insider, weather, cost of living, and HOA updates, and SHALL run Maya as an always-on group responder.

#### Scenario: Dedup blocks repeat

- **WHEN** an article or listing URL was already posted
- **THEN** the job skips it without error

### Requirement: Instagram scheduled posting

The system SHALL post rotated listing/rental/tip/market content to Instagram `@mahogany.calgary` on the configured schedule using a cached session.

#### Scenario: No new content

- **WHEN** rotation selects a type with no unseen items
- **THEN** the job exits successfully without uploading

### Requirement: Secrets and deploy isolation

The system SHALL load credentials from environment only, deploy under `/opt/mahogany`, expose `/api/build-id` on port 3004, and MUST NOT commit secrets to git.

#### Scenario: Health check

- **WHEN** deploy smoke requests `/api/build-id`
- **THEN** a build identifier matching the deployed revision is returned
