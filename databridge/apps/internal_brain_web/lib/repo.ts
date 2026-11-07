// Where the source code is published, if anywhere. Set at build time with NEXT_PUBLIC_IB_REPO_URL
// (e.g. https://git.example.com/org/repo) and optionally NEXT_PUBLIC_IB_REPO_BRANCH (default main).
// Unset: no repository link or QR code is shown.
export const REPO_URL = (process.env.NEXT_PUBLIC_IB_REPO_URL ?? '').trim().replace(/\/+$/, '');
export const REPO_BRANCH = (process.env.NEXT_PUBLIC_IB_REPO_BRANCH ?? '').trim() || 'main';
/** The URL without its scheme, as printed under a QR code. */
export const REPO_TEXT = REPO_URL.replace(/^https?:\/\//, '');
