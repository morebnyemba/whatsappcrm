// src/components/charts/BotPerformanceDisplay.jsx
import React from 'react';
import { FiCpu, FiCheckSquare, FiClock, FiMessageSquare, FiLoader } from 'react-icons/fi';
import { Progress } from "@/components/ui/progress"; // Assuming shadcn/ui progress
import { Label } from '@/components/ui/label';
export default function BotPerformanceDisplay({ data, isLoading }) {
  if (isLoading) {
    return <div className="flex items-center justify-center h-full"><FiLoader className="animate-spin h-8 w-8 text-slate-500"/></div>;
  }
  if (!data || Object.keys(data).length === 0) {
    return <p className="flex items-center justify-center h-full text-center text-sm text-slate-500 dark:text-slate-400">No bot performance data available.</p>;
  }

  const resolutionRate = (data.automated_resolution_rate * 100 || 0);

  return (
    <div className="flex flex-col items-center justify-center h-full space-y-4 p-4 text-center">
      <div className="w-full max-w-xs">
        <div className="mb-1 flex justify-between">
            <Label htmlFor="resolution-rate" className="text-sm font-medium text-slate-600 dark:text-slate-300">Automated Resolution</Label>
            <span className="text-sm font-bold text-purple-600 dark:text-purple-400">{resolutionRate.toFixed(0)}%</span>
        </div>
        <Progress value={resolutionRate} id="resolution-rate" className="w-full h-3 [&>div]:bg-purple-500" />
      </div>

      <div className="text-sm text-slate-600 dark:text-slate-300">
        Avg. Bot Response: <span className="font-bold text-lg text-slate-700 dark:text-slate-100">{data.avg_bot_response_time_seconds?.toFixed(1) || 'N/A'}s</span>
      </div>
      <div className="text-sm text-slate-600 dark:text-slate-300">
        Total Incoming Processed: <span className="font-bold text-lg text-slate-700 dark:text-slate-100">{data.total_incoming_messages_processed || 'N/A'}</span>
      </div>
      <p className="mt-4 text-xs italic text-slate-500 dark:text-slate-400">
        (More detailed charts or breakdowns can be added here)
      </p>
    </div>
  );
}