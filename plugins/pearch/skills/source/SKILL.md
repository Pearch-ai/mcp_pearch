---
name: source
description: "Executive candidate sourcing via Pearch.ai. Trigger with 'source candidates', 'найди кандидатов', 'source for [position]', 'поиск кандидатов', 'exec search', 'talent search', or when the user asks to find people for a hiring position. Runs a multi-query search pipeline, evaluates candidates against hiring criteria, and produces a ranked shortlist."
---

# /source — Executive Candidate Sourcing

Multi-query sourcing pipeline using Pearch.ai MCP tools. Finds candidates that single queries miss by combining title-based, experience-based, and alumni-based search strategies.

## Usage

```
/source Head of People Experience
/source [position name or description]
/source              ← will ask which position
```

## Pipeline

### Step 0: Preparation

1. **Identify position.** If the user names a position, look for the matching file in `Hiring/` directory of the current vault (or Manychat vault). Read the position file for context: scope, team size, must-haves, anti-patterns.
2. **Read evaluation criteria.** Read `Hiring/hiring-criteria.md` for the 7-dim scoring rubric and company values.
3. **Title expansion.** From the position title, generate 10-15 title variations that companies use for the same role. Include Director/Head/VP variants, L&D/Development/Experience/Culture/Talent/Programs synonyms. This compensates for naming variance across companies.
4. **Identify target companies.** Based on position domain, generate a list of 5-10 companies where ideal candidates might work or have worked. Consider: direct competitors, adjacent companies, same-stage B2B SaaS, same-function leaders. These will be used in custom_filters.

### Step 1: Type A — Title + Company Type (current-state search)

Search for candidates who currently hold a matching title at a matching company type.

```
search_people(
  query="[expanded titles] at [company type] with [key requirements]. Based in [location].",
  limit=20,
  insights=true,
  profile_scoring=true
)
```

This catches **obvious matches** — people currently in the right role at the right type of company.

### Step 2: Type A+ — Title + custom_filters.companies (full-history search)

Search for candidates with matching titles who have **ever worked** at target companies. This is the critical query that finds people who left tech for non-tech companies but have the right experience.

```
search_people(
  query="[expanded titles] — experienced in [key functions]. Based in [location].",
  limit=25,
  insights=false,
  profile_scoring=true,
  custom_filters={"companies": ["Target1", "Target2", ...]}
)
```

**Why limit=25:** Pearch ranking has variance; candidates with non-tech current roles rank lower. Higher limit catches them.

**Why custom_filters.companies:** This field searches across ALL career history, not just current role. It's the single most important parameter for exec sourcing — it finds strong candidates invisible to NL queries alone.

### Step 3: Type B — Function Description (title-agnostic search)

Search by describing the **work**, not the **title**. No job title in query — purely what the person has done.

```
search_people(
  query="[description of work: built X, led Y, implemented Z] at high-growth companies in [location]. [experience years]+.",
  limit=20,
  insights=false,
  profile_scoring=true
)
```

This catches **non-standard titles** — people who do the right work under a different name.

### Step 4: Deduplicate + Evaluate

1. **Merge** results from all three queries. Remove duplicates by `docid`.
2. **Score** each unique candidate using the 7-Dimensional Profile Scoring rubric (see below).
3. **Check** against position-specific anti-patterns and red flags.
4. **Rank** by composite score.
5. **Select top 5-10** for the shortlist.

### Step 5: Output

Create two files in `Hiring/Sourcing/{Position Name}/`:

**search-log.md** — query parameters, thread IDs, pool sizes, credits spent.

**shortlist.md** — ranked candidates with:
- Name, current title, company, location, LinkedIn
- 7-dim scores table
- Composite score
- Why this candidate (2-3 sentences)
- Risks (what to probe in interview)
- Fit to company values

## 7-Dimensional Profile Scoring

Score each dimension 1-5. Trajectory and Scope expansion have highest weight.

| # | Dimension | What to assess | Weight |
|---|-----------|---------------|--------|
| 1 | **Trajectory shape** | Promotions every 2-3 years (accelerating) vs plateau 5+ years | High |
| 2 | **Scope expansion** | Team growth 5→25→50 = compounding leadership. 5→8→12 = ceiling | High |
| 3 | **Company quality arc** | Strong→weak (red) vs weak→strong (green) | Medium |
| 4 | **Tenure distribution** | Serial <18 months = never completed a full cycle | Medium |
| 5 | **Team-following** | Did reports follow them to new companies? Strongest leadership signal | High |
| 6 | **Crisis/turnaround** | Experience in downturns, pivots, restructurings | Medium |
| 7 | **Board/advisory roles** | External validation, network quality | Low |

**Important:** Years of experience is one of the worst predictors (validity 0.18). De-weight in favor of trajectory signals.

## Credit Budget

| Query | Estimated cost |
|-------|---------------|
| Type A (20 results, insights) | ~40 credits |
| Type A+ (25 results, no insights) | ~25 credits |
| Type B (20 results, no insights) | ~20 credits |
| **Total per position** | **~85 credits** |

Always report credits remaining after search.

## Key Principles

1. **Success Profile, not JD.** The search should be informed by what success looks like in 18 months, not a generic job description.
2. **custom_filters.companies is the power tool.** It searches ALL career history. Always use it for Type A+.
3. **Never rely on a single query.** Single queries have systematic blind spots — title mismatch, company type mismatch, or both.
4. **Candidates who left tech are invisible to NL alone.** Type A+ with custom_filters.companies is the only reliable way to find them.
5. **Culture-add, not culture-fit.** Look for complementary strengths, not clones of current team.
6. **No contact data by default.** Don't enable reveal_emails/phones unless explicitly asked. Respect privacy, save credits.

## Position-Specific Context

If the vault contains `Hiring/hiring-criteria.md`, read it for:
- Company values (evaluate culture alignment)
- Leadership principles (if available)
- Red flags and green signals specific to this org

If the position file contains a `## Search Strategy Notes` section, use those hints for target companies and regional preferences.
