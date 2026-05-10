# Wiki Lint — Health Check Report

You are performing a health check on the PageFly knowledge base. The automated integrity system has already run deterministic auto-fixes (ghost reference removal, orphan connection backlinks, DB orphan registration). Your job is to **analyze and report** on issues that require human judgment.

## Already Auto-Fixed (by code, before you run)

These are handled deterministically — do NOT attempt to fix them again:
- Ghost references (source_doc_ids / references pointing to deleted docs)
- Orphan connection backlinks (concepts missing backlinks to their connection articles)
- DB ↔ filesystem sync (path updates, missing DB records)

## Your Analysis Tasks

### 1. Duplicate Documents
- If two knowledge documents have near-identical titles or content:
- Note the duplicate pair in the report with recommendation to merge
- Do NOT auto-delete — flag for human review

### 2. Misclassification Suspects
- Documents in wrong category based on their title/content
- Flag with suggested correct category

### 3. Coverage Gaps
- Knowledge categories with many docs but few wiki compilations
- Important concepts mentioned in 3+ docs but lacking their own wiki page

### 4. Stale Content
- Wiki articles whose source documents were updated after the article
- Summary articles that haven't been refreshed

### 5. Data Integrity
- Review the automated integrity report (provided above your prompt)
- Highlight patterns (e.g., repeated failures, categories with many issues)

## Output Format

Write your report as a lint article (article_type: "lint"):

```markdown
# Wiki Lint Report — {date}

## Summary
- X issues found, Y auto-fixed (by system), Z need human attention

## Auto-Fixed (by system)
(summarize what the automated integrity check fixed — from the report above)

## Needs Human Attention
(list issues you found, with specific actionable suggestions)

## Health Metrics
- Total knowledge docs: X
- Total wiki articles: X
- Orphan rate: X%
- Coverage score: X%
```

Write in the same language as the majority of the wiki content.
