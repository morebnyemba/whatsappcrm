// src/components/charts/ConversationTrendChart.jsx
import React from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { FiLoader } from 'react-icons/fi';
import { Label } from '@/components/ui/label';
// Helper to format date ticks on XAxis if needed
const formatDateTick = (tickItem) => {
  // Assuming tickItem is "YYYY-MM-DD"
  const date = new Date(tickItem + "T00:00:00"); // Ensure parsing as local/UTC consistently
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
};

export default function ConversationTrendChart({ data, isLoading }) {
  if (isLoading) {
    return <div className="flex items-center justify-center h-full"><FiLoader className="animate-spin h-8 w-8 text-slate-500"/></div>;
  }
  if (!data || data.length === 0) {
    return <p className="flex items-center justify-center h-full text-center text-sm text-slate-500 dark:text-slate-400">No conversation trend data available to display.</p>;
  }

  // Determine a suitable Y-axis domain if needed, or let recharts auto-calculate
  // const maxMessages = Math.max(...data.map(d => d.total_messages), 0);
  // const yAxisDomain = [0, Math.ceil(maxMessages / 10) * 10 + 10]; // Example: round up to next 10

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 5, right: 10, left: -25, bottom: 5 }}> {/* Adjusted margins */}
        <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.2} className="dark:stroke-slate-600 stroke-slate-300" />
        <XAxis 
          dataKey="date" 
          tickFormatter={formatDateTick} 
          tick={{ fontSize: 10 }} 
          className="dark:fill-slate-400 fill-slate-600"
          axisLine={{ className: "dark:stroke-slate-600 stroke-slate-300" }}
          tickLine={{ className: "dark:stroke-slate-600 stroke-slate-300" }}
        />
        <YAxis 
          tick={{ fontSize: 10 }} 
          className="dark:fill-slate-400 fill-slate-600"
          axisLine={{ className: "dark:stroke-slate-600 stroke-slate-300" }}
          tickLine={{ className: "dark:stroke-slate-600 stroke-slate-300" }}
          // domain={yAxisDomain} // Optional: if you want to set y-axis domain
        />
        <Tooltip
          contentStyle={{
            backgroundColor: 'hsl(var(--card))', // Use theme colors
            borderColor: 'hsl(var(--border))',
            borderRadius: '0.5rem',
            fontSize: '0.75rem', // text-xs
            color: 'hsl(var(--card-foreground))'
          }}
          labelStyle={{ marginBottom: '0.25rem', fontWeight: '600' }}
          cursor={{ strokeDasharray: '3 3', strokeOpacity: 0.5 }}
        />
        <Legend wrapperStyle={{fontSize: "0.75rem", paddingTop: "10px"}}/>
        <Line type="monotone" dataKey="incoming_messages" name="Incoming" stroke="#34D399" strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 6 }} />
        <Line type="monotone" dataKey="outgoing_messages" name="Outgoing" stroke="#60A5FA" strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 6 }} />
        <Line type="monotone" dataKey="total_messages" name="Total" stroke="#A78BFA" strokeWidth={2.5} dot={{ r: 3 }} activeDot={{ r: 6 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}