export function waitForMcpRetry(until: number): Promise<void> {
  const delay = until - Date.now();
  return delay > 0 ? new Promise((resolve) => { setTimeout(resolve, delay); }) : Promise.resolve();
}

// A newer request invalidates the read in progress. Coalesce overlapping requests
// into one follow-up read, accepting only the final response.
export class McpRefresh<T> {
  private revision = 0;
  private pending: Promise<void> | null = null;

  get busy(): boolean { return this.pending !== null; }

  request(read: () => Promise<T>, accept: (value: T) => void): Promise<void> {
    this.revision += 1;
    if (this.pending) return this.pending;
    this.pending = this.run(read, accept).finally(() => { this.pending = null; });
    return this.pending;
  }

  private async run(read: () => Promise<T>, accept: (value: T) => void) {
    let revision: number;
    do {
      revision = this.revision;
      const result = await read();
      if (revision === this.revision) accept(result);
    } while (revision !== this.revision);
  }
}
