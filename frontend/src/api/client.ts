import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios'

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')

interface RetryableRequest extends InternalAxiosRequestConfig {
  _ticketflowRetried?: boolean
}

export const apiClient = axios.create({
  baseURL: apiBaseUrl,
  headers: { 'Content-Type': 'application/json' },
})

const ACCESS_TOKEN_KEY = 'ticketflow.access'
const REFRESH_TOKEN_KEY = 'ticketflow.refresh'

export const tokenStore = {
  getAccess: () => sessionStorage.getItem(ACCESS_TOKEN_KEY),
  getRefresh: () => sessionStorage.getItem(REFRESH_TOKEN_KEY),
  save: (access: string, refresh: string) => {
    sessionStorage.setItem(ACCESS_TOKEN_KEY, access)
    sessionStorage.setItem(REFRESH_TOKEN_KEY, refresh)
  },
  saveAccess: (access: string) => sessionStorage.setItem(ACCESS_TOKEN_KEY, access),
  clear: () => {
    sessionStorage.removeItem(ACCESS_TOKEN_KEY)
    sessionStorage.removeItem(REFRESH_TOKEN_KEY)
  },
}

apiClient.interceptors.request.use((config) => {
  const accessToken = tokenStore.getAccess()
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const request = error.config as RetryableRequest | undefined
    const refreshToken = tokenStore.getRefresh()
    const isAuthEndpoint = request?.url?.includes('/auth/token/')

    if (
      error.response?.status !== 401 ||
      !request ||
      request._ticketflowRetried ||
      !refreshToken ||
      isAuthEndpoint
    ) {
      return Promise.reject(error)
    }

    request._ticketflowRetried = true
    try {
      const response = await axios.post<{ access: string }>(
        `${apiBaseUrl}/auth/token/refresh/`,
        { refresh: refreshToken },
      )
      tokenStore.saveAccess(response.data.access)
      request.headers.Authorization = `Bearer ${response.data.access}`
      return apiClient(request)
    } catch (refreshError) {
      tokenStore.clear()
      window.dispatchEvent(new Event('ticketflow:session-expired'))
      return Promise.reject(refreshError)
    }
  },
)

export function getApiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as
      | { detail?: string | string[]; [key: string]: unknown }
      | undefined
    if (typeof data?.detail === 'string') return data.detail
    if (Array.isArray(data?.detail)) return data.detail.join(' ')
    if (data) {
      const messages = Object.values(data)
        .flatMap((value) => (Array.isArray(value) ? value : [value]))
        .filter((value): value is string => typeof value === 'string')
      if (messages.length) return messages.join(' ')
    }
    if (!error.response) return 'Unable to reach TicketFlow. Check your connection and try again.'
  }
  return 'Something went wrong. Please try again.'
}
