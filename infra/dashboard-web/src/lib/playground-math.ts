const INLINE_OPEN_PATTERNS = [/\\\\\(/g, /\\\(/g];
const INLINE_CLOSE_PATTERNS = [/\\\\\)/g, /\\\)/g];
const BLOCK_OPEN_PATTERNS = [/\\\\\[/g, /\\\[/g];
const BLOCK_CLOSE_PATTERNS = [/\\\\\]/g, /\\\]/g];
const BLOCK_OPEN_PLACEHOLDER = "__QFINZERO_MATH_BLOCK_OPEN__";
const BLOCK_CLOSE_PLACEHOLDER = "__QFINZERO_MATH_BLOCK_CLOSE__";

function replaceAllPatterns(input: string, patterns: RegExp[], replacement: string): string {
  return patterns.reduce((acc, pattern) => acc.replace(pattern, replacement), input);
}

/**
 * Normalize common LaTeX delimiters to dollar-based style so markdown math renderers
 * can reliably parse streamed assistant output.
 */
export function normalizeMathDelimiters(input: string): string {
  let normalized = input;
  // Use placeholders so inline replacements do not collapse `$$` to `$`.
  normalized = replaceAllPatterns(normalized, BLOCK_OPEN_PATTERNS, BLOCK_OPEN_PLACEHOLDER);
  normalized = replaceAllPatterns(normalized, BLOCK_CLOSE_PATTERNS, BLOCK_CLOSE_PLACEHOLDER);
  normalized = replaceAllPatterns(normalized, INLINE_OPEN_PATTERNS, "$");
  normalized = replaceAllPatterns(normalized, INLINE_CLOSE_PATTERNS, "$");
  normalized = normalized.split(BLOCK_OPEN_PLACEHOLDER).join("$$");
  normalized = normalized.split(BLOCK_CLOSE_PLACEHOLDER).join("$$");
  return normalized;
}
