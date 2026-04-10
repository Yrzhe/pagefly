import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '',
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('pagefly_token')
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  // Let axios set correct Content-Type for FormData (with boundary)
  if (config.data instanceof FormData) {
    config.headers.delete('Content-Type')
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('pagefly_token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default api
