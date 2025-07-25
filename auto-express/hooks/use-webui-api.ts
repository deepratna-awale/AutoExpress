/**
 * React hooks for interacting with the Stable Diffusion WebUI API
 */

import { useState, useEffect, useCallback } from 'react';
import type {
  APIResponse,
  StableDiffusionProcessingTxt2Img,
  ProgressResponse,
  ProgressRequest,
} from '../lib/webui-types';

interface UseAPIOptions {
  immediate?: boolean;
  onSuccess?: (data: any) => void;
  onError?: (error: string) => void;
}

interface APIState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

/**
 * Generic hook for making API calls
 */
export function useAPI<T = any>(
  endpoint: string,
  options: UseAPIOptions & { method?: string; body?: any; baseUrl?: string } = {}
) {
  const [state, setState] = useState<APIState<T>>({
    data: null,
    loading: false,
    error: null,
  });

  const execute = useCallback(async (customBody?: any, customBaseUrl?: string) => {
    setState(prev => ({ ...prev, loading: true, error: null }));

    try {
      const requestOptions: RequestInit = {
        method: options.method || 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
      };

      if (customBody || options.body) {
        requestOptions.body = JSON.stringify(customBody || options.body);
      }

      // Build URL with baseUrl query parameter if provided
      const baseUrl = customBaseUrl || options.baseUrl;
      let url = `/api${endpoint}`;
      if (baseUrl) {
        const params = new URLSearchParams({ baseUrl });
        url += `?${params.toString()}`;
      }

      const response = await fetch(url, requestOptions);
      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.error || 'API request failed');
      }

      setState({
        data: result,
        loading: false,
        error: null,
      });

      options.onSuccess?.(result);
      return result;
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown error';
      setState({
        data: null,
        loading: false,
        error: errorMessage,
      });

      options.onError?.(errorMessage);
      throw err;
    }
  }, [endpoint, options.method, options.body, options.baseUrl, options.onSuccess, options.onError]);

  useEffect(() => {
    if (options.immediate) {
      execute();
    }
  }, [execute, options.immediate]);

  return {
    ...state,
    execute,
    refetch: execute,
  };
}

/**
 * Hook for checking WebUI health status
 */
export function useWebUIHealth() {
  return useAPI('/internal/ping', {
    immediate: true,
    method: 'GET',
  });
}

/**
 * Hook for getting WebUI system information
 */
export function useWebUIInfo() {
  return useAPI('/info', {
    immediate: false,
    method: 'GET',
  });
}

/**
 * Hook for getting WebUI configuration
 */
export function useWebUIConfig() {
  return useAPI('/config', {
    immediate: false,
    method: 'GET',
  });
}

/**
 * Hook for text-to-image generation
 */
export function useTxt2Img() {
  const [progress, setProgress] = useState<ProgressResponse | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);

  const generate = useCallback(async (params: StableDiffusionProcessingTxt2Img) => {
    try {
      const response = await fetch('/api/sd-queue/txt2img', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(params),
      });

      const result = await response.json();
      
      if (!response.ok) {
        throw new Error(result.error || 'Failed to generate image');
      }

      // Extract task ID from response if available
      if (result.task_id) {
        setTaskId(result.task_id);
      }

      return result;
    } catch (error) {
      throw error;
    }
  }, []);

  const checkProgress = useCallback(async (progressParams?: ProgressRequest) => {
    if (!taskId && !progressParams?.id_task) return null;

    try {
      const response = await fetch('/api/internal/progress', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          id_task: taskId,
          ...progressParams,
        }),
      });

      const result = await response.json();
      
      if (!response.ok) {
        throw new Error(result.error || 'Failed to get progress');
      }

      setProgress(result);
      return result;
    } catch (error) {
      console.error('Error checking progress:', error);
      return null;
    }
  }, [taskId]);

  return {
    generate,
    checkProgress,
    progress,
    taskId,
  };
}

/**
 * Hook for getting available LoRAs
 */
export function useLoRAs() {
  return useAPI('/sdapi/v1/loras', {
    immediate: false,
    method: 'GET',
  });
}

/**
 * Hook for refreshing LoRAs
 */
export function useRefreshLoRAs() {
  return useAPI('/sdapi/v1/refresh-loras', {
    immediate: false,
    method: 'POST',
  });
}

/**
 * Hook for ControlNet model list
 */
export function useControlNetModels() {
  return useAPI('/controlnet/model_list', {
    immediate: false,
    method: 'GET',
  });
}

/**
 * Hook for getting available models
 */
export function useModels() {
  return useAPI('/sdapi/v1/sd-models', {
    immediate: false,
    method: 'GET',
  });
}

/**
 * Hook for getting available samplers
 */
export function useSamplers() {
  return useAPI('/sdapi/v1/samplers', {
    immediate: false,
    method: 'GET',
  });
}

/**
 * Hook for getting available schedulers
 */
export function useSchedulers() {
  return useAPI('/sdapi/v1/schedulers', {
    immediate: false,
    method: 'GET',
  });
}

/**
 * Hook for ControlNet detection
 */
export function useControlNetDetect() {
  return useAPI('/controlnet/detect', {
    immediate: false,
    method: 'POST',
  });
}

/**
 * Hook for file upload
 */
export function useFileUpload() {
  const [uploadState, setUploadState] = useState<APIState<any>>({
    data: null,
    loading: false,
    error: null,
  });

  const upload = useCallback(async (files: FileList | File[]) => {
    setUploadState(prev => ({ ...prev, loading: true, error: null }));

    try {
      const formData = new FormData();
      
      Array.from(files).forEach((file, index) => {
        formData.append(`files`, file);
      });

      const response = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      });

      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.error || 'Upload failed');
      }

      setUploadState({
        data: result,
        loading: false,
        error: null,
      });

      return result;
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Upload failed';
      setUploadState({
        data: null,
        loading: false,
        error: errorMessage,
      });
      throw err;
    }
  }, []);

  return {
    ...uploadState,
    upload,
  };
}

/**
 * Hook for background removal
 */
export function useRemoveBackground() {
  return useAPI('/rembg', {
    immediate: false,
    method: 'POST',
  });
}

/**
 * Hook for queue status
 */
export function useQueueStatus() {
  const [status, setStatus] = useState(null);
  const [isPolling, setIsPolling] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const response = await fetch('/api/queue/status');
      const result = await response.json();
      
      if (response.ok) {
        setStatus(result);
      }
      
      return result;
    } catch (error) {
      console.error('Error fetching queue status:', error);
      return null;
    }
  }, []);

  const startPolling = useCallback((interval = 2000) => {
    setIsPolling(true);
    
    const pollInterval = setInterval(() => {
      fetchStatus();
    }, interval);

    return () => {
      clearInterval(pollInterval);
      setIsPolling(false);
    };
  }, [fetchStatus]);

  useEffect(() => {
    fetchStatus(); // Initial fetch
  }, [fetchStatus]);

  return {
    status,
    isPolling,
    fetchStatus,
    startPolling,
  };
}

/**
 * Custom hook for managing WebUI connection status
 */
export function useWebUIConnection() {
  const [isConnected, setIsConnected] = useState<boolean | null>(null);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const checkConnection = useCallback(async () => {
    try {
      const response = await fetch('/api/internal/ping');
      const connected = response.ok;
      setIsConnected(connected);
      setLastChecked(new Date());
      return connected;
    } catch {
      setIsConnected(false);
      setLastChecked(new Date());
      return false;
    }
  }, []);

  useEffect(() => {
    checkConnection();
    
    // Check connection every 30 seconds
    const interval = setInterval(checkConnection, 30000);
    
    return () => clearInterval(interval);
  }, [checkConnection]);

  return {
    isConnected,
    lastChecked,
    checkConnection,
  };
}

export default {
  useAPI,
  useWebUIHealth,
  useWebUIInfo,
  useWebUIConfig,
  useTxt2Img,
  useModels,
  useSamplers,
  useSchedulers,
  useLoRAs,
  useRefreshLoRAs,
  useControlNetModels,
  useControlNetDetect,
  useFileUpload,
  useRemoveBackground,
  useQueueStatus,
  useWebUIConnection,
};
