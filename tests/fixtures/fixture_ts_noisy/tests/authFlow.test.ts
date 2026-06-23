import { resolveAuthenticatedUser, validateLoginToken } from '@core/authFlow';

export function testResolveAuthenticatedUser() {
  return resolveAuthenticatedUser('very-long-token') !== null;
}

export function testValidateLoginToken() {
  return validateLoginToken('very-long-token') === true;
}
