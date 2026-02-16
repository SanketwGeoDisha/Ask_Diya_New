import { useState, useEffect, useRef } from "react";
import "@/App.css";
import axios from "axios";
import { Button } from "./components/ui/button";
import { Input } from "./components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./components/ui/card";
import { Badge } from "./components/ui/badge";
import { Progress } from "./components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./components/ui/tabs";
import { ScrollArea } from "./components/ui/scroll-area";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "./components/ui/accordion";
import {
  Search,
  GraduationCap,
  Building2,
  TrendingUp,
  Users,
  Award,
  BookOpen,
  Briefcase,
  Globe,
  CheckCircle,
  XCircle,
  Clock,
  AlertCircle,
  Download,
  RefreshCw,
  ChevronRight,
  Sparkles,
  ExternalLink,
  Atom,
  WifiOff,
  Wifi
} from "lucide-react";
import { useNetworkStatus } from "./hooks/useNetworkStatus";
import { exportToCSV, exportToJSON, exportWithWorker } from "./utils/exportUtils";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Polling configuration
const POLL_INTERVAL_MS = 2000;  // 2 seconds
const MAX_POLL_TIME_MS = 5 * 60 * 1000;  // 5 minutes

// Category icons mapping
const categoryIcons = {
  "Infrastructure & Sustainability": Building2,
  "Graduate Outcome & Employability": Briefcase,
  "Innovation, Startup & IP": Sparkles,
  "Research Quality & Impact Output": BookOpen,
  "Admissions (Quality & Diversity)": Users,
  "Industry Integration": Globe,
  "Teaching and Learning Environment": GraduationCap,
  "Student Experience and Well-Being": Award,
  "Internationalization & Global Reputation": Globe,
  "Quality Assurance and NEP Implementation": CheckCircle,
};

// Confidence colors
const confidenceColors = {
  high: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  medium: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  low: "bg-red-500/20 text-red-400 border-red-500/30",
};

// Source priority colors
const priorityColors = {
  high: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  medium: "bg-purple-500/20 text-purple-400 border-purple-500/30",
  low: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  unknown: "bg-gray-500/20 text-gray-400 border-gray-500/30",
};

function App() {
  const [collegeName, setCollegeName] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [currentAudit, setCurrentAudit] = useState(null);
  const [recentAudits, setRecentAudits] = useState([]);
  const [activeTab, setActiveTab] = useState("overview");
  const [networkError, setNetworkError] = useState(null);
  const [isExporting, setIsExporting] = useState(false);
  const [pollTimeout, setPollTimeout] = useState(false);

  const pollIntervalRef = useRef(null);
  const pollStartTimeRef = useRef(null);

  // Monitor network status
  const { isOnline, wasOffline } = useNetworkStatus();

  // Load recent audits on mount
  useEffect(() => {
    loadRecentAudits();
  }, []);

  // Poll for audit updates with timeout
  useEffect(() => {
    if (currentAudit?.status === "processing" && currentAudit?.id) {
      // Reset timeout flag
      setPollTimeout(false);
      pollStartTimeRef.current = Date.now();

      pollIntervalRef.current = setInterval(async () => {
        // Check if polling has exceeded maximum time
        const elapsedTime = Date.now() - pollStartTimeRef.current;
        if (elapsedTime > MAX_POLL_TIME_MS) {
          console.warn('Polling timeout reached after 5 minutes');
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
          setPollTimeout(true);
          setIsLoading(false);
          return;
        }

        try {
          const response = await axios.get(`${API}/audit/${currentAudit.id}`);
          setCurrentAudit(response.data);
          setNetworkError(null);  // Clear any previous network errors

          if (response.data.status === "completed" || response.data.status === "failed") {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
            setIsLoading(false);
            loadRecentAudits();
          }
        } catch (error) {
          console.error("Poll error:", error);

          // Handle network errors
          if (!navigator.onLine) {
            setNetworkError('You are offline. Polling paused.');
          } else if (error.code === 'ECONNABORTED' || error.message.includes('timeout')) {
            setNetworkError('Connection timeout. Retrying...');
          } else if (error.response?.status >= 500) {
            setNetworkError('Server error. Retrying...');
          }
          // Don't clear interval on error, let it retry
        }
      }, POLL_INTERVAL_MS);
    }

    // Cleanup function - CRITICAL for preventing memory leaks
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
  }, [currentAudit?.id, currentAudit?.status]);

  const loadRecentAudits = async () => {
    try {
      const response = await axios.get(`${API}/audits?limit=10`, { timeout: 10000 });
      setRecentAudits(response.data.audits || []);
      setNetworkError(null);
    } catch (error) {
      console.error("Failed to load audits:", error);
      if (!navigator.onLine) {
        setNetworkError('You are offline. Please check your connection.');
      }
    }
  };

  const startAudit = async () => {
    if (!collegeName.trim()) return;

    // Check network status
    if (!isOnline) {
      setNetworkError('You are offline. Please check your internet connection.');
      return;
    }

    setIsLoading(true);
    setActiveTab("overview");
    setNetworkError(null);
    setPollTimeout(false);

    try {
      const response = await axios.post(`${API}/audit/start`, {
        college_name: collegeName.trim()
      }, { timeout: 15000 });

      setCurrentAudit({
        id: response.data.audit_id,
        college_name: collegeName.trim(),
        status: "processing",
        progress: 0,
        progress_message: "Starting audit...",
        results: [],
        summary: {}
      });
    } catch (error) {
      console.error("Start audit error:", error);
      setIsLoading(false);

      // Better error messages
      if (!navigator.onLine) {
        setNetworkError('You are offline. Please check your connection and try again.');
      } else if (error.code === 'ECONNABORTED') {
        setNetworkError('Request timeout. The server is taking too long to respond.');
      } else if (error.response?.status >= 500) {
        setNetworkError('Server error. Please try again later.');
      } else {
        const errorMsg = error.response?.data?.detail || error.message || "Unknown error";
        setNetworkError(`Failed to start audit: ${errorMsg}`);
      }
    }
  };

  const stopAudit = async () => {
    if (!currentAudit?.id) {
      console.error('No audit ID found');
      return;
    }

    // Update UI immediately to show cancellation
    setCurrentAudit(prev => ({
      ...prev,
      status: "cancelled",
      progress_message: "Cancelling audit...",
      progress: prev.progress || 0
    }));
    setIsLoading(false);

    // Clear polling interval immediately
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }

    try {
      console.log(`Attempting to cancel audit: ${currentAudit.id}`);
      const response = await axios.post(`${API}/audit/${currentAudit.id}/cancel`);
      console.log('Cancel response:', response.data);

      // Update with final cancelled state
      setCurrentAudit(prev => ({
        ...prev,
        status: "cancelled",
        progress_message: "Audit cancelled by user"
      }));

      // Reload audits list after a short delay
      setTimeout(() => loadRecentAudits(), 500);
    } catch (error) {
      console.error("Stop audit error:", error);
      const errorMessage = error.response?.data?.detail || error.message || "Unknown error";

      // Only alert if it's a real error (not already cancelled/completed)
      if (error.response?.status !== 400) {
        alert(`Failed to stop audit: ${errorMessage}`);
      }
    }
  };

  const loadAudit = async (auditId) => {
    try {
      const response = await axios.get(`${API}/audit/${auditId}`);
      setCurrentAudit(response.data);
      setCollegeName(response.data.college_name || "");
      setActiveTab("overview");
    } catch (error) {
      console.error("Load audit error:", error);
    }
  };

  const exportResults = async () => {
    if (!currentAudit?.results) return;

    setIsExporting(true);
    try {
      // Use optimized export for large datasets
      if (currentAudit.results.length > 1000) {
        await exportWithWorker(
          currentAudit.results,
          'csv',
          `${currentAudit.college_name}_audit_${new Date().toISOString().split('T')[0]}.csv`
        );
      } else {
        exportToCSV(
          currentAudit.results,
          `${currentAudit.college_name}_audit_${new Date().toISOString().split('T')[0]}.csv`
        );
      }
    } catch (error) {
      console.error('Export failed:', error);
      alert('Failed to export data: ' + error.message);
    } finally {
      setIsExporting(false);
    }
  };

  const exportJSON = async () => {
    if (!currentAudit) return;

    setIsExporting(true);
    try {
      const jsonData = {
        college_name: currentAudit.college_name,
        audit_date: currentAudit.created_at,
        time_taken_seconds: currentAudit.time_taken_seconds,
        summary: currentAudit.summary,
        results: currentAudit.results.map(r => ({
          kpi_name: r.kpi_name,
          category: r.category,
          value: r.value,
          evidence_quote: r.evidence_quote,
          source_url: r.source_url,
          source_type: r.source_type,
          system_confidence: r.system_confidence || r.confidence,
          llm_confidence: r.llm_confidence,
          llm_confidence_reason: r.llm_confidence_reason,
          source_priority: r.source_priority,
          data_year: r.data_year,
          recency: r.recency
        }))
      };

      // Use optimized export for large datasets
      if (currentAudit.results.length > 1000) {
        await exportWithWorker(
          jsonData,
          'json',
          `${currentAudit.college_name}_audit_${new Date().toISOString().split('T')[0]}.json`
        );
      } else {
        exportToJSON(
          jsonData,
          `${currentAudit.college_name}_audit_${new Date().toISOString().split('T')[0]}.json`
        );
      }
    } catch (error) {
      console.error('Export JSON failed:', error);
      alert('Failed to export JSON: ' + error.message);
    } finally {
      setIsExporting(false);
    }
  };

  // Group results by category
  const groupedResults = currentAudit?.results?.reduce((acc, result) => {
    const category = result.category || "Other";
    if (!acc[category]) acc[category] = [];
    acc[category].push(result);
    return acc;
  }, {}) || {};

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white">
      {/* Grain overlay */}
      <div className="fixed inset-0 pointer-events-none opacity-[0.03] z-50">
        <div className="absolute inset-0" style={{ backgroundImage: "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E\")" }}></div>
      </div>

      {/* Header */}
      <header className="border-b border-white/5 backdrop-blur-xl bg-[#0a0a0f]/80 sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-teal-400 to-cyan-600 flex items-center justify-center">
              <GraduationCap className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-semibold tracking-tight font-['Space_Grotesk']">AskDiya</h1>
              <p className="text-xs text-white/40">KPI Intelligence Platform</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {currentAudit?.results?.length > 0 && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={exportResults}
                  disabled={isExporting}
                  className="border-white/10 bg-white/5 hover:bg-white/10"
                  data-testid="export-csv-btn"
                >
                  {isExporting ? (
                    <>
                      <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                      Exporting...
                    </>
                  ) : (
                    <>
                      <Download className="w-4 h-4 mr-2" />
                      Export CSV
                    </>
                  )}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={exportJSON}
                  disabled={isExporting}
                  className="border-white/10 bg-white/5 hover:bg-white/10"
                  data-testid="export-json-btn"
                >
                  {isExporting ? (
                    <>
                      <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                      Exporting...
                    </>
                  ) : (
                    <>
                      <Download className="w-4 h-4 mr-2" />
                      Export JSON
                    </>
                  )}
                </Button>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        {/* Network Status Banner */}
        {!isOnline && (
          <div className="mb-4 p-4 bg-red-500/10 border border-red-500/20 rounded-lg flex items-center gap-3">
            <WifiOff className="w-5 h-5 text-red-400" />
            <div className="flex-1">
              <p className="text-sm font-medium text-red-300">You are offline</p>
              <p className="text-xs text-red-400/70">Check your internet connection to continue auditing.</p>
            </div>
          </div>
        )}

        {wasOffline && isOnline && (
          <div className="mb-4 p-4 bg-green-500/10 border border-green-500/20 rounded-lg flex items-center gap-3">
            <Wifi className="w-5 h-5 text-green-400" />
            <div className="flex-1">
              <p className="text-sm font-medium text-green-300">Back online</p>
              <p className="text-xs text-green-400/70">Your connection has been restored.</p>
            </div>
          </div>
        )}

        {/* Network Error with Retry */}
        {networkError && (
          <div className="mb-4 p-4 bg-yellow-500/10 border border-yellow-500/20 rounded-lg">
            <div className="flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-yellow-400 mt-0.5" />
              <div className="flex-1">
                <p className="text-sm font-medium text-yellow-300 mb-1">Connection Issue</p>
                <p className="text-xs text-yellow-400/70 mb-3">{networkError}</p>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setNetworkError(null);
                    if (currentAudit?.id) {
                      // Restart polling if there's an active audit
                      window.location.reload();
                    }
                  }}
                  className="border-yellow-500/30 bg-yellow-500/5 hover:bg-yellow-500/10 text-yellow-300"
                >
                  <RefreshCw className="w-4 h-4 mr-2" />
                  Retry
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Polling Timeout Warning */}
        {pollTimeout && (
          <div className="mb-4 p-4 bg-orange-500/10 border border-orange-500/20 rounded-lg">
            <div className="flex items-start gap-3">
              <Clock className="w-5 h-5 text-orange-400 mt-0.5" />
              <div className="flex-1">
                <p className="text-sm font-medium text-orange-300 mb-1">Taking Longer Than Expected</p>
                <p className="text-xs text-orange-400/70 mb-3">
                  This audit is taking longer than usual (over 5 minutes). The audit may still be processing on the server.
                </p>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setPollTimeout(false);
                    setIsLoading(true);
                    pollStartTimeRef.current = Date.now();
                    // Trigger polling restart by updating audit status
                    setCurrentAudit(prev => ({ ...prev, status: 'processing' }));
                  }}
                  className="border-orange-500/30 bg-orange-500/5 hover:bg-orange-500/10 text-orange-300"
                >
                  <RefreshCw className="w-4 h-4 mr-2" />
                  Continue Checking
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Search Section */}
        <section className="mb-8">
          <Card className="bg-white/[0.02] border-white/5 backdrop-blur-sm">
            <CardContent className="p-6">
              <div className="flex flex-col md:flex-row gap-4">
                <div className="flex-1 relative">
                  <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-white/30" />
                  <Input
                    placeholder="Enter college name (e.g., IIT Bombay, NIT Trichy, VIT Vellore)"
                    value={collegeName}
                    onChange={(e) => setCollegeName(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && startAudit()}
                    className="pl-12 h-14 bg-white/5 border-white/10 text-white placeholder:text-white/30 text-lg"
                    data-testid="college-input"
                  />
                </div>
                <Button
                  onClick={startAudit}
                  disabled={isLoading || !collegeName.trim()}
                  className="h-14 px-8 bg-gradient-to-r from-teal-500 to-cyan-600 hover:from-teal-400 hover:to-cyan-500 text-white font-semibold"
                  data-testid="start-audit-btn"
                >
                  {isLoading ? (
                    <>
                      <RefreshCw className="w-5 h-5 mr-2 animate-spin" />
                      Analyzing...
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-5 h-5 mr-2" />
                      Start Audit
                    </>
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>
        </section>

        {/* Progress Section */}
        {currentAudit?.status === "processing" && (
          <section className="mb-8" data-testid="progress-section">
            <Card className="bg-white/[0.02] border-white/5">
              <CardContent className="p-6">
                <div className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-4 flex-1">
                    <RefreshCw className="w-8 h-8 text-teal-400 animate-spin" />
                    <div className="flex-1">
                      <p className="text-white font-medium mb-1">
                        {currentAudit.progress_message || "Processing..."}
                      </p>
                      {currentAudit.progress > 0 && (
                        <div className="flex items-center gap-3">
                          <Progress value={currentAudit.progress} className="h-2 flex-1" />
                          <span className="text-sm text-white/50">{currentAudit.progress}%</span>
                        </div>
                      )}
                    </div>
                  </div>
                  <Button
                    variant="outline"
                    onClick={stopAudit}
                    className="border-red-500/30 bg-red-500/10 hover:bg-red-500/20 text-red-400"
                  >
                    <XCircle className="w-4 h-4 mr-2" />
                    Stop
                  </Button>
                </div>
              </CardContent>
            </Card>
          </section>
        )}

        {/* Cancelled Message */}
        {currentAudit?.status === "cancelled" && (
          <section className="mb-8" data-testid="cancelled-section">
            <Card className="bg-amber-500/5 border-amber-500/20">
              <CardContent className="p-6">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-xl bg-amber-500/20 flex items-center justify-center">
                    <AlertCircle className="w-6 h-6 text-amber-400" />
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold text-white mb-1">Audit Cancelled</h3>
                    <p className="text-white/60">The audit was stopped before completion. You can start a new audit anytime.</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </section>
        )}

        {/* Results Section */}
        {currentAudit?.status === "completed" && currentAudit?.results?.length > 0 && (
          <section data-testid="results-section">
            <Tabs value={activeTab} onValueChange={setActiveTab}>
              <div className="flex items-center justify-between mb-6">
                <TabsList className="bg-white/5 border border-white/10">
                  <TabsTrigger value="overview" className="data-[state=active]:bg-teal-500/20 data-[state=active]:text-teal-400">
                    Overview
                  </TabsTrigger>
                  <TabsTrigger value="category" className="data-[state=active]:bg-teal-500/20 data-[state=active]:text-teal-400">
                    By Category
                  </TabsTrigger>
                  <TabsTrigger value="all" className="data-[state=active]:bg-teal-500/20 data-[state=active]:text-teal-400">
                    All KPIs
                  </TabsTrigger>
                </TabsList>
              </div>

              {/* Overview Tab */}
              <TabsContent value="overview">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
                  <Card className="bg-white/[0.02] border-white/5">
                    <CardContent className="p-6">
                      <div className="flex items-center gap-4">
                        <div className="w-12 h-12 rounded-xl bg-teal-500/20 flex items-center justify-center">
                          <CheckCircle className="w-6 h-6 text-teal-400" />
                        </div>
                        <div>
                          <p className="text-3xl font-bold text-white">{currentAudit.summary?.data_found || 0}</p>
                          <p className="text-white/50 text-sm">Data Found</p>
                        </div>
                      </div>
                    </CardContent>
                  </Card>

                  <Card className="bg-white/[0.02] border-white/5">
                    <CardContent className="p-6">
                      <div className="flex items-center gap-4">
                        <div className="w-12 h-12 rounded-xl bg-amber-500/20 flex items-center justify-center">
                          <AlertCircle className="w-6 h-6 text-amber-400" />
                        </div>
                        <div>
                          <p className="text-3xl font-bold text-white">{currentAudit.summary?.data_not_found || 0}</p>
                          <p className="text-white/50 text-sm">Not Found</p>
                        </div>
                      </div>
                    </CardContent>
                  </Card>

                  <Card className="bg-white/[0.02] border-white/5">
                    <CardContent className="p-6">
                      <div className="flex items-center gap-4">
                        <div className="w-12 h-12 rounded-xl bg-cyan-500/20 flex items-center justify-center">
                          <Award className="w-6 h-6 text-cyan-400" />
                        </div>
                        <div>
                          <p className="text-3xl font-bold text-white">{currentAudit.summary?.populated_percentage || 0}%</p>
                          <p className="text-white/50 text-sm">Populated</p>
                        </div>
                      </div>
                    </CardContent>
                  </Card>

                  <Card className="bg-white/[0.02] border-white/5">
                    <CardContent className="p-6">
                      <div className="flex items-center gap-4">
                        <div className="w-12 h-12 rounded-xl bg-purple-500/20 flex items-center justify-center">
                          <Clock className="w-6 h-6 text-purple-400" />
                        </div>
                        <div>
                          <p className="text-3xl font-bold text-white">
                            {currentAudit.time_taken_seconds
                              ? currentAudit.time_taken_seconds >= 60
                                ? `${Math.floor(currentAudit.time_taken_seconds / 60)}m ${Math.round(currentAudit.time_taken_seconds % 60)}s`
                                : `${Math.round(currentAudit.time_taken_seconds)}s`
                              : "N/A"}
                          </p>
                          <p className="text-white/50 text-sm">Time Taken</p>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </div>

                {/* Category Summary */}
                <Card className="bg-white/[0.02] border-white/5">
                  <CardHeader>
                    <CardTitle className="text-lg">Category Breakdown</CardTitle>
                    <CardDescription>Data populated by category</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-4">
                      {Object.entries(currentAudit.summary?.categories || {}).map(([category, stats]) => {
                        const Icon = categoryIcons[category] || BookOpen;
                        const percentage = stats.total > 0 ? Math.round((stats.found / stats.total) * 100) : 0;

                        return (
                          <div key={category} className="flex items-center gap-4">
                            <div className="w-10 h-10 rounded-lg bg-white/5 flex items-center justify-center">
                              <Icon className="w-5 h-5 text-teal-400" />
                            </div>
                            <div className="flex-1">
                              <div className="flex items-center justify-between mb-1">
                                <span className="text-sm font-medium text-white/80">{category}</span>
                                <span className="text-sm text-white/50">{stats.found}/{stats.total}</span>
                              </div>
                              <Progress value={percentage} className="h-1.5 bg-white/10" />
                            </div>
                            <span className="text-sm font-medium text-teal-400 w-12 text-right">{percentage}%</span>
                          </div>
                        );
                      })}
                    </div>
                  </CardContent>
                </Card>
              </TabsContent>

              {/* By Category Tab */}
              <TabsContent value="category">
                <Accordion type="multiple" className="space-y-4">
                  {Object.entries(groupedResults).map(([category, results]) => {
                    const Icon = categoryIcons[category] || BookOpen;
                    const foundCount = results.filter(r => !["data not found", "error", "processing error", "not available"].includes(String(r.value ?? '').toLowerCase())).length;

                    return (
                      <AccordionItem key={category} value={category} className="border border-white/5 rounded-xl bg-white/[0.02] overflow-hidden">
                        <AccordionTrigger className="px-6 py-4 hover:no-underline hover:bg-white/5">
                          <div className="flex items-center gap-4">
                            <div className="w-10 h-10 rounded-lg bg-teal-500/20 flex items-center justify-center">
                              <Icon className="w-5 h-5 text-teal-400" />
                            </div>
                            <div className="text-left">
                              <h3 className="font-semibold text-white">{category}</h3>
                              <p className="text-sm text-white/50">{foundCount}/{results.length} KPIs with data</p>
                            </div>
                          </div>
                        </AccordionTrigger>
                        <AccordionContent>
                          <div className="px-6 pb-4 space-y-3">
                            {results.map((result, idx) => (
                              <KPICard key={idx} result={result} />
                            ))}
                          </div>
                        </AccordionContent>
                      </AccordionItem>
                    );
                  })}
                </Accordion>
              </TabsContent>

              {/* All KPIs Tab */}
              <TabsContent value="all">
                <Card className="bg-white/[0.02] border-white/5">
                  <CardContent className="p-0">
                    <ScrollArea className="h-[600px]">
                      <div className="p-4 space-y-3">
                        {currentAudit.results.map((result, idx) => (
                          <KPICard key={idx} result={result} showCategory />
                        ))}
                      </div>
                    </ScrollArea>
                  </CardContent>
                </Card>
              </TabsContent>
            </Tabs>
          </section>
        )}

        {/* Recent Audits */}
        {recentAudits.length > 0 && !currentAudit && (
          <section data-testid="recent-audits">
            <h2 className="text-xl font-semibold mb-4 text-white/80">Recent Audits</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {recentAudits.map((audit) => (
                <Card
                  key={audit.id}
                  className="bg-white/[0.02] border-white/5 cursor-pointer hover:bg-white/[0.04] transition-colors"
                  onClick={() => loadAudit(audit.id)}
                  data-testid={`audit-card-${audit.id}`}
                >
                  <CardContent className="p-4">
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="font-medium text-white truncate">{audit.college_name}</h3>
                      <Badge
                        variant={audit.status === "completed" ? "default" : "secondary"}
                        className={`text-xs ${audit.status === "completed" ? "" :
                          audit.status === "cancelled" ? "bg-amber-500/20 text-amber-400 border-amber-500/30" :
                            audit.status === "failed" ? "bg-red-500/20 text-red-400 border-red-500/30" : ""
                          }`}
                      >
                        {audit.status}
                      </Badge>
                    </div>
                    <div className="flex items-center gap-4 text-sm text-white/50">
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {new Date(audit.created_at).toLocaleDateString()}
                      </span>
                      {audit.summary?.populated_percentage && (
                        <span className="flex items-center gap-1">
                          <TrendingUp className="w-3 h-3" />
                          {audit.summary.populated_percentage}% populated
                        </span>
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </section>
        )}

        {/* Empty State */}
        {!currentAudit && recentAudits.length === 0 && (
          <section className="text-center py-16" data-testid="empty-state">
            <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-teal-500/20 to-cyan-600/20 flex items-center justify-center mx-auto mb-6">
              <GraduationCap className="w-10 h-10 text-teal-400" />
            </div>
            <h2 className="text-2xl font-semibold text-white mb-2">Start Your First Audit</h2>
            <p className="text-white/50 max-w-md mx-auto">
              Enter a college name above to analyze 75+ Key Performance Indicators across infrastructure, placements, research, and more.
            </p>
          </section>
        )}
      </main>
    </div>
  );
}

// Helper function to format KPI values for display
function formatValue(value) {
  if (value === null || value === undefined) {
    return "N/A";
  }
  if (typeof value === 'boolean') {
    return value ? "Yes" : "No";
  }
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  if (typeof value === 'object') {
    // Handle objects like {facilities: [], achievements: []}
    return Object.entries(value)
      .map(([key, val]) => {
        const formattedVal = Array.isArray(val) ? val.join(", ") : String(val);
        return `${key}: ${formattedVal}`;
      })
      .join(" | ");
  }
  return String(value);
}

// KPI Card Component
function KPICard({ result, showCategory = false }) {
  const isFound = !["data not found", "error", "processing error", "not available"].includes(String(result.value ?? '').toLowerCase());
  const displayValue = formatValue(result.value);

  // Get both confidence levels
  const systemConfidence = result.system_confidence || result.confidence || 'low';
  const llmConfidence = result.llm_confidence || result.confidence || 'low';
  const sourcePriority = result.source_priority || 'unknown';

  return (
    <div className={`p-4 rounded-lg border ${isFound ? "bg-white/[0.02] border-white/10" : "bg-red-500/5 border-red-500/10"}`}>
      <div className="flex items-start justify-between gap-4 mb-3">
        <div className="flex-1">
          <h4 className="font-medium text-white text-sm">{result.kpi_name}</h4>
          {showCategory && (
            <p className="text-xs text-white/40 mt-0.5">{result.category}</p>
          )}
        </div>

        {/* Dual Confidence Badges */}
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-white/40 uppercase tracking-wide font-medium">Sys:</span>
            <Badge
              variant="outline"
              className={`text-[10px] px-2 py-0.5 ${confidenceColors[systemConfidence] || confidenceColors.low}`}
              title={`System confidence based on source priority: ${sourcePriority}`}
            >
              {systemConfidence}
            </Badge>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-white/40 uppercase tracking-wide font-medium">LLM:</span>
            <Badge
              variant="outline"
              className={`text-[10px] px-2 py-0.5 ${confidenceColors[llmConfidence] || confidenceColors.low}`}
              title={result.llm_confidence_reason || "LLM's self-assessment of data reliability"}
            >
              {llmConfidence}
            </Badge>
          </div>
          {result.recency && result.recency !== 'unknown' && (
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-white/40 uppercase tracking-wide font-medium">Data:</span>
              <Badge
                variant="outline"
                className={`text-[10px] px-2 py-0.5 ${result.recency === 'high' ? 'border-green-500/30 bg-green-500/10 text-green-400' :
                  result.recency === 'medium' ? 'border-yellow-500/30 bg-yellow-500/10 text-yellow-400' :
                    'border-orange-500/30 bg-orange-500/10 text-orange-400'
                  }`}
                title={`Data from ${result.data_year || 'unknown year'}`}
              >
                {result.data_year || result.recency}
              </Badge>
            </div>
          )}
        </div>
      </div>

      {/* Source Priority Badge */}
      {result.source_priority && result.source_priority !== 'unknown' && (
        <div className="mb-2">
          <Badge
            variant="outline"
            className={`text-[10px] ${priorityColors[sourcePriority] || priorityColors.unknown}`}
          >
            {sourcePriority === 'high' && '🏛️ Official/Government'}
            {sourcePriority === 'medium' && '📚 Wikipedia'}
            {sourcePriority === 'low' && '📊 Aggregator'}
          </Badge>
        </div>
      )}

      <div className={`text-lg font-semibold mb-2 ${isFound ? "text-teal-400" : "text-white/30"}`}>
        {displayValue}
      </div>

      {result.evidence_quote && result.evidence_quote !== "Not found in search results" && (
        <p className="text-xs text-white/50 line-clamp-2 mb-2">
          "{result.evidence_quote}"
        </p>
      )}

      {/* LLM Confidence Reason */}
      {result.llm_confidence_reason && result.llm_confidence_reason !== "Not provided by LLM" && result.llm_confidence_reason !== "Not explicitly provided by LLM" && (
        <p className="text-[10px] text-white/40 italic mb-2">
          💭 LLM: {result.llm_confidence_reason}
        </p>
      )}

      {/* Source URL - More Prominent */}
      {result.source_url && result.source_url !== "N/A" && result.source_url !== "Not Available" ? (
        <div className="mt-3 pt-3 border-t border-white/10">
          <div className="flex items-start gap-2">
            <div className="flex items-center gap-1.5 text-[10px] text-white/50 uppercase tracking-wide font-medium pt-0.5">
              <ExternalLink className="w-3 h-3 flex-shrink-0" />
              Source:
            </div>
            <a
              href={result.source_url.startsWith("http") ? result.source_url : `https://${result.source_url}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-teal-400 hover:text-teal-300 hover:underline break-all flex-1"
              title={result.source_url}
            >
              {result.source_url}
            </a>
          </div>
        </div>
      ) : (
        <div className="mt-3 pt-3 border-t border-white/10">
          <div className="flex items-center gap-1.5 text-[10px] text-white/30 uppercase tracking-wide font-medium">
            <ExternalLink className="w-3 h-3 flex-shrink-0" />
            Source: Not Available
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
