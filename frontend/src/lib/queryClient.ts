import { QueryCache, QueryClient } from "@tanstack/react-query"
import { logger } from "./logger"

export function createQueryClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        logger.error("[Query]", String(query.queryKey), error instanceof Error ? error.message : String(error))
      },
    }),
    defaultOptions: {
      // The backend is local: the default "online" mode would pause every request while the
      // machine is offline, and the library shows empty with no error (I-61).
      queries: {
        networkMode: "always",
        staleTime: 60_000,
        gcTime: 60_000,
        refetchOnWindowFocus: false,
        retry: 2,
        retryDelay: 1000,
      },
      mutations: { networkMode: "always" },
    },
  })
}
