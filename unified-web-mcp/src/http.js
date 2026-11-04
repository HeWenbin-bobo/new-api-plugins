import { Buffer } from 'node:buffer';
import { lookup } from 'node:dns/promises';
import { isIP } from 'node:net';
import { Agent } from 'undici';
import { InputError, ProviderError } from './errors.js';

function ipv4Value(address) {
  return address.split('.').reduce((value, part) => (value << 8) | Number(part), 0) >>> 0;
}

function isNonPublicIpv4(address) {
  const value = ipv4Value(address);
  const ranges = [
    [0x00000000, 0x00ffffff],
    [0x0a000000, 0x0affffff],
    [0x64400000, 0x647fffff],
    [0x7f000000, 0x7fffffff],
    [0xa9fe0000, 0xa9feffff],
    [0xac100000, 0xac1fffff],
    [0xc0000000, 0xc00000ff],
    [0xc0000200, 0xc00002ff],
    [0xc0586300, 0xc05863ff],
    [0xc0a80000, 0xc0a8ffff],
    [0xc6120000, 0xc613ffff],
    [0xc6336400, 0xc63364ff],
    [0xcb007100, 0xcb0071ff],
    [0xe0000000, 0xffffffff],
  ];
  return ranges.some(([first, last]) => value >= first && value <= last);
}

function ipv6Words(address) {
  let expanded = address.toLowerCase();
  if (expanded.includes('%')) return null;

  if (expanded.includes('.')) {
    const separator = expanded.lastIndexOf(':');
    const ipv4 = expanded.slice(separator + 1);
    if (isIP(ipv4) !== 4) return null;
    const value = ipv4Value(ipv4);
    expanded = `${expanded.slice(0, separator)}:${(value >>> 16).toString(16)}:${(value & 0xffff).toString(16)}`;
  }

  const halves = expanded.split('::');
  if (halves.length > 2) return null;
  const left = halves[0] ? halves[0].split(':') : [];
  const right = halves[1] ? halves[1].split(':') : [];
  if (halves.length === 1 && left.length !== 8) return null;
  if (left.length + right.length > 8) return null;
  const parts = [...left, ...Array(8 - left.length - right.length).fill('0'), ...right];
  if (parts.length !== 8 || parts.some(part => !/^[0-9a-f]{1,4}$/.test(part))) return null;
  return parts.map(part => Number.parseInt(part, 16));
}

function isNonPublicIpv6(address) {
  const words = ipv6Words(address);
  if (!words) return true;
  const [a, b, c, d, e, f, g, h] = words;

  if (words.every(word => word === 0)) return true;
  if ([a, b, c, d, e].every(word => word === 0) && (f === 0 || f === 0xffff)) {
    return isNonPublicIpv4(`${(g >>> 8) & 0xff}.${g & 0xff}.${(h >>> 8) & 0xff}.${h & 0xff}`);
  }
  if (a === 0x64 && b === 0xff9b && c === 0 && d === 0 && e === 0 && f === 0) {
    return isNonPublicIpv4(`${(g >>> 8) & 0xff}.${g & 0xff}.${(h >>> 8) & 0xff}.${h & 0xff}`);
  }
  if (a === 0x64 && b === 0xff9b && c === 1) return true;
  if ((a & 0xfe00) === 0xfc00 || (a & 0xffc0) === 0xfe80 || (a & 0xffc0) === 0xfec0 || (a & 0xff00) === 0xff00) return true;
  if (a === 0x0100 && b === 0 && c === 0 && d === 0) return true;
  if (a === 0x2001 && b === 0) return true;
  if (a === 0x2001 && b === 0x0002 && c === 0) return true;
  if (a === 0x2001 && (b === 0x0db8 || (b & 0xfff0) === 0x0020)) return true;
  if (a === 0x2002) {
    return isNonPublicIpv4(`${(b >>> 8) & 0xff}.${b & 0xff}.${(c >>> 8) & 0xff}.${c & 0xff}`);
  }
  return false;
}

function isNonPublicAddress(address) {
  const family = isIP(address);
  if (family === 4) return isNonPublicIpv4(address);
  if (family === 6) return isNonPublicIpv6(address);
  return true;
}

export function createPublicLookup({ lookup: resolve = lookup } = {}) {
  return (hostname, options, callback) => {
    Promise.resolve()
      .then(() => resolve(hostname, { ...options, all: true, verbatim: true }))
      .then(addresses => {
        if (!Array.isArray(addresses) || addresses.length === 0 || addresses.some(entry => (
          !entry || isNonPublicAddress(entry.address)
        ))) {
          throw new InputError('Fetch URL must resolve to a public address');
        }
        return addresses.map(entry => ({
          address: entry.address,
          family: isIP(entry.address),
        }));
      })
      .then(validated => {
        if (options?.all) {
          callback(null, validated);
        } else {
          callback(null, validated[0].address, validated[0].family);
        }
      }, callback);
  };
}

export function createPublicDispatcher(options) {
  return new Agent({ connect: { lookup: createPublicLookup(options) } });
}

export async function readBoundedResponseText(response, {
  maxBytes = 1_000_000,
  provider,
  operation,
  signal,
} = {}) {
  signal?.throwIfAborted();
  const tooLarge = () => new ProviderError(`${operation} response exceeded ${maxBytes} bytes`, {
    provider,
    retryable: true,
  });
  const declaredLength = Number(response.headers.get('content-length'));
  if (Number.isFinite(declaredLength) && declaredLength > maxBytes) {
    await response.body?.cancel().catch(() => {});
    throw tooLarge();
  }
  if (!response.body) return '';

  const reader = response.body.getReader();
  const chunks = [];
  let length = 0;
  let onAbort;
  const aborted = signal ? new Promise((_, reject) => {
    onAbort = () => reject(signal.reason);
    signal.addEventListener('abort', onAbort, { once: true });
  }) : null;

  try {
    while (true) {
      const pending = reader.read();
      const { done, value } = aborted
        ? await Promise.race([pending, aborted])
        : await pending;
      if (done) break;
      if (length + value.byteLength > maxBytes) throw tooLarge();
      chunks.push(Buffer.from(value.buffer, value.byteOffset, value.byteLength));
      length += value.byteLength;
    }
  } catch (error) {
    await reader.cancel().catch(() => {});
    throw error;
  } finally {
    if (onAbort) signal.removeEventListener('abort', onAbort);
  }

  return Buffer.concat(chunks, length).toString('utf8');
}

export async function assertPublicUrl(input, { allowPrivate = false, lookup: resolve = lookup } = {}) {
  let url;
  try {
    url = new URL(input);
  } catch {
    throw new InputError('Fetch URL must be a valid HTTP(S) URL');
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new InputError('Fetch URL must use HTTP(S)');
  }
  if (url.username || url.password) {
    throw new InputError('Fetch URL must not contain credentials');
  }
  if (allowPrivate) return url;

  const hostname = url.hostname.replace(/^\[|\]$/g, '').replace(/\.$/, '').toLowerCase();
  if (hostname === 'localhost' || hostname.endsWith('.localhost')) {
    throw new InputError('Fetch URL must resolve to a public address');
  }
  if (isIP(hostname)) {
    if (isNonPublicAddress(hostname)) throw new InputError('Fetch URL must resolve to a public address');
    return url;
  }

  const addresses = await resolve(hostname, { all: true, verbatim: true });
  if (!Array.isArray(addresses) || addresses.length === 0 || addresses.some(entry => (
    !entry || isNonPublicAddress(entry.address)
  ))) {
    throw new InputError('Fetch URL must resolve to a public address');
  }
  return url;
}
