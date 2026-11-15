import { api } from './api';
import { createAuthController } from './auth';
export const auth = createAuthController(api);
