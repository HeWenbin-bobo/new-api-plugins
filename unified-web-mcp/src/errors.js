export class ProviderError extends Error {
  constructor(message, { provider, retryable = true, status } = {}) {
    super(message);
    this.name = 'ProviderError';
    this.provider = provider;
    this.retryable = retryable;
    this.status = status;
  }
}

export class InputError extends Error {
  constructor(message) {
    super(message);
    this.name = 'InputError';
  }
}
