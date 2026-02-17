import { useState, useEffect } from 'react';

/**
 * Hook to monitor online/offline network status
 * @returns {Object} { isOnline, wasOffline }
 */
export function useNetworkStatus() {
  const [isOnline, setIsOnline] = useState(
    typeof navigator !== 'undefined' ? navigator.onLine : true
  );
  const [wasOffline, setWasOffline] = useState(false);

  useEffect(() => {
    // Handle online event
    const handleOnline = () => {
      setIsOnline(true);
      console.log('Network: Back online');
    };

    // Handle offline event
    const handleOffline = () => {
      setIsOnline(false);
      setWasOffline(true);
      console.log('Network: Offline');
    };

    // Add event listeners
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    // Cleanup
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  return { isOnline, wasOffline };
}
