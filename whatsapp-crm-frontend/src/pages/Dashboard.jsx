// Filename: src/pages/Dashboard.jsx
// Main dashboard page - Enhanced with dynamic data fetching and integrated Recharts components

import React, { useState, useEffect, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  FiUsers, FiMessageCircle, FiBarChart2, FiActivity, FiAlertCircle,
  FiCheckCircle, FiSettings, FiZap, FiHardDrive, FiTrendingUp, FiCpu, FiList, FiLoader
} from 'react-icons/fi'; // FiExternalLink was not used, removed for tidiness
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';

// Import your chart components (adjust path if needed)
import ConversationTrendChart from '@/components/charts/ConversationTrendChat';
import BotPerformanceDisplay from '@/components/charts/BotPerfomanceDisplay';

// --- API Configuration & Helper ---
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const getAuthToken = () => localStorage.getItem('accessToken'); // Replace with your actual auth logic

async function apiCall(endpoint, method = 'GET', body = null, isPaginatedFallback = false) {
  const token = getAuthToken();
  const headers = {
    ...(token && { 'Authorization': `Bearer ${token}` }),
    ...(!body || !(body instanceof FormData) && { 'Content-Type': 'application/json' }),
  };
  const config = { method, headers, ...(body && !(body instanceof FormData) && { body: JSON.stringify(body) }) };

  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, config);
    if (!response.ok) {
      let errorData = { detail: `Request failed: ${response.status} ${response.statusText}` };
      try {
        const contentType = response.headers.get("content-type");
        if (contentType && contentType.indexOf("application/json") !== -1) { errorData = await response.json(); }
        else { errorData.detail = (await response.text()) || errorData.detail; }
      } catch (e) { console.error("Failed to parse error response:", e); }
      const errorMessage = errorData.detail ||
                           (typeof errorData === 'object' && errorData !== null && !errorData.detail ?
                             Object.entries(errorData).map(([k,v])=>`${k.replace(/_/g, " ")}: ${Array.isArray(v) ? v.join(', ') : v}`).join('; ') :
                             `API Error ${response.status}`);
      const err = new Error(errorMessage); err.data = errorData; throw err;
    }
    if (response.status === 204 || (response.headers.get("content-length") || "0") === "0") {
      return isPaginatedFallback ? { results: [], count: 0 } : null;
    }
    const data = await response.json();
    // Ensure paginated fallback returns consistent structure
    if (isPaginatedFallback) {
        return { 
            results: data.results || (Array.isArray(data) ? data : []), 
            count: data.count || (Array.isArray(data) ? data.length : 0) 
        };
    }
    return data;
  } catch (error) {
    console.error(`API call to ${method} ${API_BASE_URL}${endpoint} failed:`, error);
    if (!error.message.includes("(toasted)")) {
        toast.error(error.message || 'An API error occurred. Check console.');
        error.message += " (toasted)";
    }
    throw error;
  }
}

// Initial structure for stats cards
const initialStatCardsDefinition = [
  { id: "active_conversations_count", title: "Active Conversations", defaultIcon: <FiMessageCircle/>, linkTo: "/conversation", colorScheme: "green", trendKey: "active_conversations_trend_text", valueSuffix: "" },
  { id: "new_contacts_today", title: "New Contacts (Today)", defaultIcon: <FiUsers/>, linkTo: "/contacts", colorScheme: "emerald", trendKey: "total_contacts_text", valueSuffix: "" }, // Changed trendKey
  { id: "messages_sent_24h", title: "Messages Sent (24h)", defaultIcon: <FiTrendingUp/>, linkTo: null, colorScheme: "lime", trendKey: "messages_sent_automated_percent_text", valueSuffix: "" },
  { id: "meta_configs_total", title: "Meta API Configs", defaultIcon: <FiHardDrive/>, linkTo: "/api-settings", colorScheme: "teal", trendKey: "meta_config_active_name_text", valueSuffix: "" }, // Changed trendKey
  { id: "pending_human_handovers", title: "Pending Handovers", defaultIcon: <FiAlertCircle/>, linkTo: "/contacts?filter=needs_intervention", colorScheme: "red", trendKey: "pending_human_handovers_priority_text", valueSuffix: "" },
];

// Icon mapping for recent activities
const activityIcons = {
  default: FiActivity, FiMessageCircle: FiMessageCircle, FiUsers: FiUsers,
  FiSettings: FiSettings, FiZap: FiZap, FiCheckCircle: FiCheckCircle, FiAlertCircle: FiAlertCircle,
};

const getCardStyles = (colorScheme) => {
  switch (colorScheme) {
    case "green": return { bgColor: "bg-green-50 dark:bg-green-900/40", borderColor: "border-green-500/60 dark:border-green-600", textColor: "text-green-700 dark:text-green-300", iconColor: "text-green-600 dark:text-green-400" };
    case "emerald": return { bgColor: "bg-emerald-50 dark:bg-emerald-900/40", borderColor: "border-emerald-500/60 dark:border-emerald-600", textColor: "text-emerald-700 dark:text-emerald-300", iconColor: "text-emerald-600 dark:text-emerald-400" };
    case "lime": return { bgColor: "bg-lime-50 dark:bg-lime-900/40", borderColor: "border-lime-500/60 dark:border-lime-600", textColor: "text-lime-700 dark:text-lime-300", iconColor: "text-lime-600 dark:text-lime-400" };
    case "teal": return { bgColor: "bg-teal-50 dark:bg-teal-900/40", borderColor: "border-teal-500/60 dark:border-teal-600", textColor: "text-teal-700 dark:text-teal-300", iconColor: "text-teal-600 dark:text-teal-400" };
    case "red": return { bgColor: "bg-red-50 dark:bg-red-900/40", borderColor: "border-red-500/60 dark:border-red-600", textColor: "text-red-700 dark:text-red-300", iconColor: "text-red-600 dark:text-red-400" };
    default: return { bgColor: "bg-gray-50 dark:bg-gray-900/40", borderColor: "border-gray-500/60 dark:border-gray-600", textColor: "text-gray-700 dark:text-gray-300", iconColor: "text-gray-600 dark:text-gray-400" };
  }
};

export default function Dashboard() {
  const [statsCardsData, setStatsCardsData] = useState( // Correct state variable name
    initialStatCardsDefinition.map(card => ({...card, value: "...", trend: "..."}))
  );
  const [recentActivities, setRecentActivities] = useState([]);
  const [flowInsights, setFlowInsights] = useState({ activeFlows: "...", completedToday: "...", avgSteps: "..." });
  const [conversationTrendsData, setConversationTrendsData] = useState([]);
  const [botPerformanceData, setBotPerformanceData] = useState({});

  const [systemStatus, setSystemStatus] = useState({ status: "Initializing...", color: "text-yellow-500 dark:text-yellow-400", icon: <FiLoader className="animate-spin" /> });
  const [isLoadingData, setIsLoadingData] = useState(true);
  const [loadingError, setLoadingError] = useState('');
  const navigate = useNavigate();

  const fetchData = useCallback(async () => {
    setIsLoadingData(true); setLoadingError('');
    
    try {
      const [summaryResult, configsResult] = await Promise.allSettled([
        apiCall('/crm-api/stats/summary/'),
        apiCall('/crm-api/meta/api/configs/', 'GET', null, true),
      ]);

      const summary = (summaryResult.status === "fulfilled" && summaryResult.value) ? summaryResult.value : {};
      const statsFromSummary = summary.stats_cards || {};
      const insightsFromSummary = summary.flow_insights || {};
      const chartsFromSummary = summary.charts_data || {};
      const activitiesFromSummary = summary.recent_activity_log || [];

      let newStats = JSON.parse(JSON.stringify(initialStatCardsDefinition));
      
      // Process MetaAppConfigs
      if (configsResult.status === "fulfilled" && configsResult.value) {
        const cfData = configsResult.value;
        const configCount = cfData.count;
        const activeOne = cfData.results.find(c => c.is_active);
        const metaConfigStatIdx = newStats.findIndex(s => s.id === "meta_configs_total"); // Matched key from summary
        if(metaConfigStatIdx !== -1) {
            newStats[metaConfigStatIdx].value = configCount?.toString() || "0";
            newStats[metaConfigStatIdx].trend = activeOne ? `1 Active: ${activeOne.name.substring(0,15)}...` : `${configCount || 0} Total`;
        }
      } else if (configsResult.status === "rejected") {
        const idx = newStats.findIndex(s => s.id === "meta_configs_total"); if(idx !== -1) { newStats[idx].value = "N/A"; newStats[idx].trend = "Error"; }
        setLoadingError(prev => `${prev} Meta Configs: ${configsResult.reason.message};`.trim());
      }
      
      // Update other stat cards from summaryData.stats_cards
      newStats = newStats.map(card => {
          if (card.id === "meta_configs_total") return card; // Already handled

          const summaryValue = statsFromSummary[card.id];
          if (summaryValue !== undefined && summaryValue !== null) {
              let trendText = "";
              let trendType = "neutral";
              // Example: Your backend summary for 'new_contacts_today' might provide a trend text in 'total_contacts_text'
              if (card.trendKey && statsFromSummary[card.trendKey]) {
                trendText = statsFromSummary[card.trendKey];
              } else if (card.id === "pending_human_handovers") {
                  trendType = parseInt(summaryValue) > 0 ? "negative" : "positive";
                  trendText = parseInt(summaryValue) > 0 ? `${summaryValue} require attention` : "All clear";
              }
              return {...card, value: summaryValue.toString(), trend: trendText, trendType };
          }
          return {...card, value: "N/A", trend: "N/A"};
      });
      
      setStatsCardsData(newStats); // Corrected setter name

      setFlowInsights({
          activeFlows: insightsFromSummary.active_flows_count === undefined ? "..." : insightsFromSummary.active_flows_count,
          completedToday: insightsFromSummary.flow_completions_today === undefined ? "..." : insightsFromSummary.flow_completions_today,
          avgSteps: insightsFromSummary.avg_steps_per_flow === undefined ? "..." : insightsFromSummary.avg_steps_per_flow?.toFixed(1),
      });
      setConversationTrendsData(chartsFromSummary.conversation_trends || []);
      setBotPerformanceData(chartsFromSummary.bot_performance || {});
      setRecentActivities(activitiesFromSummary.map(act => {
          const IconComponent = activityIcons[act.iconName] || activityIcons.default;
          return {...act, icon: <IconComponent className={`${act.iconColor || "text-gray-500"} h-5 w-5`} /> };
      }));
      
      const overallSuccess = [summaryResult, configsResult].every(r => r.status === 'fulfilled');
      if (overallSuccess) {
        setSystemStatus({ status: summary.system_status || "Operational", color: "text-green-500 dark:text-green-400", icon: <FiCheckCircle /> });
      } else {
        setSystemStatus({ status: "Data Error", color: "text-red-500 dark:text-red-400", icon: <FiAlertCircle /> });
      }

    } catch (error) { // Catch errors from apiCall if not handled by Promise.allSettled (e.g. if one was critical before allSettled)
      console.error("Error in fetchData orchestrator:", error);
      if (!loadingError) setLoadingError(`Failed to load dashboard data. ${error.message}`);
      setSystemStatus({ status: "System Error", color: "text-red-500 dark:text-red-400", icon: <FiAlertCircle /> });
      setStatsCardsData(initialStatCardsDefinition.map(card => ({...card, value: "N/A", trend: "Error"})));
      setFlowInsights({ activeFlows: "N/A", completedToday: "N/A", avgSteps: "N/A" });
      setRecentActivities([{id: 'err', text: 'Failed to load activities.', time:'', icon: <FiAlertCircle className="text-red-500"/>}]);
    } finally {
      setIsLoadingData(false);
    }
  }, [loadingError]); // Removed loadingError from here to prevent re-fetch loops if it's set.
                      // fetchData itself does not depend on loadingError to run.

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Run once on mount

  const CardLinkWrapper = ({ linkTo, children, className }) => {
    const baseClasses = "block h-full";
    if (linkTo) { return <Link to={linkTo} className={`${baseClasses} hover:shadow-2xl transition-shadow duration-300 ${className || ''}`}>{children}</Link>; }
    return <div className={`${baseClasses} ${className || ''}`}>{children}</div>;
  };

  const renderStatCardValue = (value) => {
    if (isLoadingData && value === "...") {
        return <FiLoader className="animate-spin h-8 w-8 inline-block opacity-70 text-current"/>;
    }
    return value;
  };

  return (
    <div className="space-y-6 md:space-y-8 pb-12">
      {/* Header */}
      <div className="flex flex-wrap justify-between items-center gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-gray-800 dark:text-gray-100">Dashboard Overview</h1>
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
            Welcome! Here's a real-time summary of your CRM activity.
          </p>
        </div>
        <div className={`flex items-center gap-2 py-1.5 px-3 rounded-full text-xs font-medium ${systemStatus.color}`}>
          {React.cloneElement(systemStatus.icon, { className: "h-4 w-4"})}
          <span>System: {systemStatus.status}</span>
        </div>
      </div>

      {loadingError && (
        <Card className="border-orange-500/70 dark:border-orange-600/70 bg-orange-50 dark:bg-orange-900/20">
            <CardContent className="p-4 text-sm text-orange-700 dark:text-orange-300 flex items-center gap-3">
                <FiAlertCircle className="h-6 w-6 flex-shrink-0"/>
                <div><span className="font-semibold">Data Loading Issue(s):</span> {loadingError.replace(/\(toasted\)/gi, '').replace(/;/g, '; ').trim()} Some data may be unavailable.</div>
            </CardContent>
        </Card>
      )}

      {/* Stats Cards Grid */}
      <div className="grid grid-cols-1 gap-4 md:gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {statsCardsData.map((stat) => {
          const styles = getCardStyles(stat.colorScheme);
          return (
            <CardLinkWrapper linkTo={stat.linkTo} key={stat.id}>
              <div className={`p-4 sm:p-5 rounded-xl shadow-lg border-l-4 ${styles.borderColor} ${styles.bgColor} flex flex-col justify-between min-h-[140px] md:min-h-[150px] h-full transition-transform hover:scale-[1.02] ${stat.linkTo ? 'cursor-pointer' : ''}`}>
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <h3 className="text-xs sm:text-sm font-semibold text-gray-600 dark:text-gray-300 truncate" title={stat.title}>{stat.title}</h3>
                    {React.cloneElement(stat.defaultIcon, {className: `h-6 w-6 opacity-70 ${styles.iconColor}`})}
                  </div>
                  <p className={`text-2xl sm:text-3xl md:text-4xl font-bold ${styles.textColor}`}>{renderStatCardValue(stat.value)}{stat.valueSuffix}</p>
                </div>
                {stat.trend && (
                  <p className={`text-xs mt-1.5 ${stat.trendType === 'positive' ? 'text-green-600 dark:text-green-400' : stat.trendType === 'negative' ? 'text-red-600 dark:text-red-400' : 'text-gray-500 dark:text-gray-400'}`}>
                    {isLoadingData && stat.trend === "..." ? <Skeleton className="h-3 w-20 inline-block dark:bg-slate-700 rounded"/> : stat.trend}
                  </p>
                )}
              </div>
            </CardLinkWrapper>
          );
        })}
      </div>

      {/* Flow Insights & Recent Activity */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 md:gap-8">
        <Card className="lg:col-span-1 dark:bg-slate-800 dark:border-slate-700 shadow-lg">
          <CardHeader>
            <CardTitle className="text-lg font-semibold dark:text-slate-100 flex items-center"><FiZap className="mr-2 text-purple-500"/>Flow Insights</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {[
              { label: "Active Flows", value: flowInsights.activeFlows, icon: <FiZap className="text-purple-500"/>, link: "/flows" },
              { label: "Completions Today", value: flowInsights.completedToday, icon: <FiCheckCircle className="text-emerald-500"/>, link: null },
              { label: "Avg. Steps/Flow", value: flowInsights.avgSteps, icon: <FiList className="text-teal-500"/>, link: null },
            ].map(item => (
              <div key={item.label} className={`flex justify-between items-center p-3 rounded-lg bg-slate-50 dark:bg-slate-700/50 ${item.link ? 'hover:bg-slate-100 dark:hover:bg-slate-700 cursor-pointer' : ''} transition-colors`}
                   onClick={item.link && !isLoadingData ? () => navigate(item.link) : undefined}
              >
                <div className="flex items-center">
                  {React.cloneElement(item.icon, {className: "h-5 w-5 mr-3 opacity-90"})}
                  <p className="text-sm text-slate-700 dark:text-slate-300 font-medium">{item.label}</p>
                </div>
                <p className="text-lg font-bold text-slate-800 dark:text-slate-100">{isLoadingData && item.value === "..." ? <FiLoader className="animate-spin h-5 w-5 inline text-slate-500"/> : item.value}</p>
              </div>
            ))}
          </CardContent>
        </Card>
        
        <Card className="lg:col-span-2 dark:bg-slate-800 dark:border-slate-700 shadow-lg">
          <CardHeader>
            <CardTitle className="text-lg font-semibold dark:text-slate-100 flex items-center"><FiActivity className="mr-2 text-blue-500"/>Recent Activity</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 max-h-72 overflow-y-auto pr-2 custom-scrollbar">
              {isLoadingData && recentActivities.length === 0 ? (
                [...Array(3)].map((_, i) => <Skeleton key={i} className="h-12 w-full dark:bg-slate-700 rounded-lg mb-2" />)
              ) : recentActivities.length === 0 ? (
                 <p className="text-sm text-slate-500 dark:text-slate-400 italic p-3 text-center">No recent activity to display.</p>
              ) : (
                recentActivities.map((activity) => (
                  <div key={activity.id} className="flex items-start space-x-3 p-2.5 bg-slate-50 dark:bg-slate-700/60 rounded-lg">
                    <span className="flex-shrink-0 mt-1 text-slate-500 dark:text-slate-400">{activity.icon || <FiActivity className="text-gray-500"/>}</span>
                    <div>
                      <p className="text-sm text-slate-700 dark:text-slate-300 leading-snug">{activity.text}</p>
                      <p className="text-xs text-slate-400 dark:text-slate-500">{new Date(activity.timestamp).toLocaleString()}</p>
                    </div>
                  </div>
                ))
              )}
            </div>
          </CardContent>
        </Card>
      </div>
      
      {/* Chart Sections - Using imported components */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 md:gap-8 mt-6 md:mt-8">
          <Card className="dark:bg-slate-800 dark:border-slate-700 shadow-lg">
              <CardHeader><CardTitle className="text-lg font-semibold dark:text-slate-100 flex items-center"><FiBarChart2 className="mr-2 text-indigo-500"/>Conversation Trends</CardTitle></CardHeader>
              <CardContent className="h-80 bg-slate-50 dark:bg-slate-700/50 rounded-md p-2 sm:p-4"> {/* Added padding */}
                  <ConversationTrendChart data={conversationTrendsData} isLoading={isLoadingData} />
              </CardContent>
          </Card>
           <Card className="dark:bg-slate-800 dark:border-slate-700 shadow-lg">
              <CardHeader><CardTitle className="text-lg font-semibold dark:text-slate-100 flex items-center"><FiCpu className="mr-2 text-rose-500"/>Bot Performance</CardTitle></CardHeader>
              <CardContent className="h-80 bg-slate-50 dark:bg-slate-700/50 rounded-md p-4 flex items-center justify-center"> {/* Ensure content is centered */}
                  <BotPerformanceDisplay data={botPerformanceData} isLoading={isLoadingData} />
              </CardContent>
          </Card>
      </div>
    </div>
  );
}