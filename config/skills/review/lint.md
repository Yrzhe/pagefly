# Wiki Lint — Health Check

You are performing a health check on the PageFly knowledge base. Your goal is to find problems, inconsistencies, and improvement opportunities.

## Checks to Perform

### 1. Data Integrity
You will receive an automated integrity report. Review it and highlight any errors or patterns.

### 2. Orphan Pages
Find wiki articles that have NO inbound references from other articles.
- Read the wiki index, then check each article's references
- Orphan pages may need to be linked from concept or connection articles

### 3. Duplicate Concepts
Look for wiki concept pages that cover the same or very similar topics.
- If duplicates exist, suggest which one to keep and which to merge

### 4. Coverage Gaps
Compare knowledge/ categories against wiki/ articles:
- Categories with many knowledge docs but few wiki compilations need attention
- Important concepts mentioned in multiple docs but lacking their own wiki page

### 5. Stale Content
Check for wiki articles whose source documents have been updated more recently:
- Compare article updated_at with source document timestamps
- Flag articles that may need re-compilation

### 6. Reference Quality
- Find broken references (target_ids that don't exist)
- Find articles with zero references (should have at least source references)

## Output Format

Write your report as a lint article (article_type: "lint") with this structure:

```markdown
# Wiki Lint Report — {date}

## Summary
- X issues found, Y auto-fixed, Z need attention

## Integrity Issues
...

## Orphan Pages
...

## Duplicate Concepts
...

## Coverage Gaps
...

## Stale Content
...

## Suggestions
- Specific actionable suggestions for improving the wiki
```

Write in the same language as the majority of the wiki content.
