import React from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';

/**
 * Error Boundary Component
 * Catches React errors and displays fallback UI
 */
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
      errorCount: 0
    };
  }

  static getDerivedStateFromError(error) {
    // Update state so the next render will show the fallback UI
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    // Log error to console (you can also send to error tracking service)
    console.error('ErrorBoundary caught an error:', error, errorInfo);
    
    this.setState(prevState => ({
      error,
      errorInfo,
      errorCount: prevState.errorCount + 1
    }));

    // Optional: Send error to logging service
    if (window.Sentry) {
      window.Sentry.captureException(error, { extra: errorInfo });
    }
  }

  handleReset = () => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null
    });
    
    // Optionally reload the page if errors persist
    if (this.state.errorCount > 2) {
      window.location.reload();
    }
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900 flex items-center justify-center p-4">
          <Card className="bg-white/[0.03] border-red-500/30 max-w-2xl w-full">
            <CardHeader>
              <CardTitle className="flex items-center gap-3 text-red-400">
                <AlertCircle className="w-8 h-8" />
                <span>Something went wrong</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-white/70">
                We encountered an unexpected error. This has been logged and we'll look into it.
              </p>
              
              {this.state.error && (
                <div className="bg-black/30 p-4 rounded-lg border border-white/10">
                  <p className="text-sm text-red-300 font-mono">
                    {this.state.error.toString()}
                  </p>
                </div>
              )}
              
              {process.env.NODE_ENV === 'development' && this.state.errorInfo && (
                <details className="bg-black/30 p-4 rounded-lg border border-white/10">
                  <summary className="text-sm text-white/50 cursor-pointer hover:text-white/70">
                    Stack Trace (Development Only)
                  </summary>
                  <pre className="text-xs text-white/40 mt-2 overflow-auto max-h-64">
                    {this.state.errorInfo.componentStack}
                  </pre>
                </details>
              )}
              
              <div className="flex gap-3">
                <Button
                  onClick={this.handleReset}
                  className="bg-teal-500 hover:bg-teal-600"
                >
                  <RefreshCw className="w-4 h-4 mr-2" />
                  Try Again
                </Button>
                
                {this.state.errorCount > 1 && (
                  <Button
                    onClick={() => window.location.reload()}
                    variant="outline"
                    className="border-white/20 text-white hover:bg-white/10"
                  >
                    Reload Page
                  </Button>
                )}
              </div>
              
              <p className="text-xs text-white/40">
                If this problem persists, please contact support or try refreshing the page.
              </p>
            </CardContent>
          </Card>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
