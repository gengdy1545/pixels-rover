import { buildCommonHeaders } from '../../../shared/api/client';
import { redirectToLogout } from '../../../shared/storage/navigation';
import type { UserInfo } from '../../../shared/types/user';

interface KratosSession {
  id: string;
  identity: {
    id: string;
    traits?: {
      email?: string;
      name?: string;
      affiliation?: string;
    };
  };
}

function mapKratosSession(session: KratosSession): UserInfo {
  const traits = session.identity.traits ?? {};
  const email = traits.email ?? '';
  return {
    id: session.identity.id,
    name: traits.name || email || session.identity.id,
    email,
    affiliation: traits.affiliation ?? '',
  };
}

async function whoami(): Promise<UserInfo> {
  const response = await fetch('/sessions/whoami', {
    method: 'GET',
    credentials: 'include',
    headers: buildCommonHeaders(),
  });
  if (!response.ok) {
    throw new Error('Authentication required');
  }
  return mapKratosSession((await response.json()) as KratosSession);
}

export const authApi = {
  me: whoami,
  getUserInfo: whoami,

  logout: async () => {
    redirectToLogout('/login');
  },
};
