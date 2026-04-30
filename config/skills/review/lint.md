# Wiki Lint — Health Check + Auto-Fix

You are performing a health check on the PageFly knowledge base. Your goal is to find problems, fix what you can, and report what needs human attention.

## IMPORTANT: You have write access. FIX problems when possible, don't just report them.

## Auto-Fix Actions (DO these directly)

### 1. Ghost References
- If a wiki article references a document ID that doesn't exist, remove the ghost reference
- Use `write_wiki_article` with `update_id` to update the article's references
- Log what you fixed in the report

### 2. Orphan Connection Pages
- If a connection article links concept A ↔ B, but concept A doesn't reference the connection:
- Read concept A, add the connection as a `related_concept` reference, update it
- This fixes the "dead end" problem

### 3. Duplicate Documents
- If two knowledge documents have near-identical titles or content:
- Note the duplicate pair in the report with recommendation to merge
- Do NOT auto-delete — flag for human review

## Report-Only Checks (flag but don't fix)

### 4. Misclassification Suspects
- Documents in "content-strategy" that aren't about content marketing
- Documents in wrong category based on their title/content
- Flag with suggested correct category

### 5. Coverage Gaps
- Knowledge categories with many docs but few wiki compilations
- Important concepts mentioned in 3+ docs but lacking their own wiki page

### 6. Stale Content
- Wiki articles whose source documents were updated after the article
- Summary articles that haven't been refreshed

### 7. Data Integrity
- Review the automated integrity report
- Highlight patterns (e.g., repeated failures)

## Output Format

Write your report as a lint article (article_type: "lint"):

```markdown
# Wiki Lint Report — {date}

## Summary
- X issues found, Y auto-fixed, Z need human attention

## Auto-Fixed
(list what you actually fixed with IDs)

## Needs Human Attention
(list issues you couldn't fix, with specific actionable suggestions)

## Health Metrics
- Total knowledge docs: X
- Total wiki articles: X
- Orphan rate: X%
- Ghost references: X (fixed/remaining)
```

Write in the same language as the majority of the wiki content.
