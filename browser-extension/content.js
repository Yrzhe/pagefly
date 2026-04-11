// Content script: extract page content and convert to markdown
// Runs in the context of the web page

function extractPage() {
  // Clone the document for Readability (it modifies the DOM)
  const clone = document.cloneNode(true);
  const article = new Readability(clone).parse();

  if (!article) {
    return {
      title: document.title,
      content: document.body.innerText.slice(0, 5000),
      url: window.location.href,
      markdown: null,
      error: 'Could not extract article content'
    };
  }

  // Convert HTML to Markdown using Turndown
  const turndown = new TurndownService({
    headingStyle: 'atx',
    codeBlockStyle: 'fenced',
    bulletListMarker: '-',
  });

  // Keep images
  turndown.addRule('images', {
    filter: 'img',
    replacement: (content, node) => {
      const alt = node.getAttribute('alt') || '';
      const src = node.getAttribute('src') || '';
      if (!src) return '';
      // Convert relative URLs to absolute
      const absoluteSrc = new URL(src, window.location.href).href;
      return `![${alt}](${absoluteSrc})`;
    }
  });

  const markdown = turndown.turndown(article.content);

  // Build full document with metadata header
  const header = [
    `# ${article.title}`,
    '',
    `> Source: ${window.location.href}`,
    article.byline ? `> Author: ${article.byline}` : null,
    `> Clipped: ${new Date().toISOString().split('T')[0]}`,
    '',
    '---',
    '',
  ].filter(Boolean).join('\n');

  return {
    title: article.title,
    byline: article.byline || '',
    url: window.location.href,
    markdown: header + markdown,
    excerpt: article.excerpt || '',
    length: article.length || 0,
  };
}

// Listen for messages from popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'extract') {
    try {
      const result = extractPage();
      sendResponse(result);
    } catch (e) {
      sendResponse({ error: e.message });
    }
  }
  return true; // async response
});
