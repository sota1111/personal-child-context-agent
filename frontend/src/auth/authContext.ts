import { createContext } from 'react'

export interface AuthContextType {
  isAuthenticated: boolean
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

// Default value is only used when a consumer renders outside the provider (never in
// this app); it keeps the type total so `useAuth` needs no null-checks.
export const AuthContext = createContext<AuthContextType>({
  isAuthenticated: false,
  loading: true,
  login: async () => {},
  logout: async () => {},
})
