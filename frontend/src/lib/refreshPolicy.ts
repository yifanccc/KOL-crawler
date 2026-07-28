export function isBlockingRefresh(hasLoaded: boolean): boolean {
  return !hasLoaded;
}

export function refreshErrorMessage(hasLoaded: boolean, message: string): string {
  return hasLoaded ? "" : message;
}
