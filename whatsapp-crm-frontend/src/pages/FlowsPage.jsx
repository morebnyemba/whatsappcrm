// src/pages/FlowsPage.jsx

import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, Link } from 'react-router-dom'; // <--- IMPORT useNavigate and Link
import { Button } from '@/components/ui/button';
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter
} from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import {
  Tooltip,
  TooltipProvider,
  TooltipTrigger,
  TooltipContent
} from '@/components/ui/tooltip';
import {
  FiPlus,
  FiEdit,
  FiTrash2,
  FiZap,
  FiToggleLeft,
  FiToggleRight,
  FiLoader,
  FiAlertCircle,
  FiMessageCircle
} from 'react-icons/fi';
import { toast } from 'sonner';

// --- API Configuration ---
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const getAuthToken = () => localStorage.getItem('accessToken');

// --- API Helper Function (ensure this is consistent with other files) ---
async function apiCall(endpoint, method = 'GET', body = null) {
  const token = getAuthToken();
  const headers = {
    ...(token && { 'Authorization': `Bearer ${token}` }),
    ...(!body || !(body instanceof FormData) && { 'Content-Type': 'application/json' }),
  };
  const config = { method, headers, ...(body && !(body instanceof FormData) && { body: JSON.stringify(body) }) };
  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, config);
    if (!response.ok) {
      let errorData = { detail: `Request failed: ${response.status}` };
      try {
        const contentType = response.headers.get("content-type");
        if (contentType && contentType.indexOf("application/json") !== -1) { errorData = await response.json(); }
        else { errorData.detail = (await response.text()) || errorData.detail; }
      } catch (e) { /* Use default error */ }
      const errorMessage = errorData.detail || Object.entries(errorData).map(([k,v])=>`${k}: ${Array.isArray(v) ? v.join(', ') : v}`).join('; ');
      const err = new Error(errorMessage); err.data = errorData; throw err;
    }
    if (response.status === 204 || (response.headers.get("content-length") || "0") === "0") return null;
    return await response.json();
  } catch (error) {
    toast.error(error.message || 'An API error occurred.'); throw error;
  }
}

export default function FlowsPage() {
  const [flows, setFlows] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const navigate = useNavigate(); // <--- Initialize useNavigate hook

  const fetchFlows = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await apiCall('/crm-api/flows/flows/'); // Uses your Django URL structure
      setFlows(data.results || data);
    } catch (err) {
      setError(err.message || "Could not fetch flows.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchFlows();
  }, [fetchFlows]);

  const handleCreateNewFlow = () => {
    navigate('/flows/new'); // <--- UPDATED: Navigate to the new flow editor page
  };

  const handleEditFlow = (flowId) => {
    navigate(`/flows/edit/${flowId}`); // <--- UPDATED: Navigate to edit page for specific flow
  };

  const handleDeleteFlow = async (flowId, flowName) => {
    if (!window.confirm(`Are you sure you want to delete the flow "${flowName}"? This action cannot be undone.`)) {
      return;
    }
    try {
      await apiCall(`/crm-api/flows/flows/${flowId}/`, 'DELETE');
      toast.success(`Flow "${flowName}" deleted successfully.`);
      setFlows(prevFlows => prevFlows.filter(flow => flow.id !== flowId));
    } catch (err) {
      // Error already toasted by apiCall
    }
  };

  const handleToggleFlowStatus = async (flow) => {
    const newStatus = !flow.is_active;
    const actionText = newStatus ? 'activating' : 'deactivating';
    toast.promise(
      apiCall(`/crm-api/flows/flows/${flow.id}/`, 'PATCH', { is_active: newStatus }),
      {
        loading: `${actionText.charAt(0).toUpperCase() + actionText.slice(1)} flow "${flow.name}"...`,
        success: (updatedFlow) => {
          setFlows(prevFlows => prevFlows.map(f => (f.id === flow.id ? updatedFlow : f)));
          return `Flow "${updatedFlow.name}" ${newStatus ? 'activated' : 'deactivated'}.`;
        },
        error: (err) => `Failed to ${actionText} flow: ${err.message}`,
      }
    );
  };

  if (isLoading && flows.length === 0) {
    return (
      <div className="flex items-center justify-center h-64">
        <FiLoader className="animate-spin h-12 w-12 text-blue-600 dark:text-blue-300" />
        <p className="ml-4 text-lg text-gray-600 dark:text-gray-300">Loading Flows...</p>
      </div>
    );
  }

  if (error && flows.length === 0) {
    return (
      <div className="container mx-auto p-6">
        <Card className="border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-900/10">
          <CardContent className="p-6 text-center text-red-700 dark:text-red-400">
            <FiAlertCircle className="h-12 w-12 mx-auto mb-3 text-red-500 dark:text-red-600" />
            <p className="text-xl font-semibold mb-2">Failed to Load Flows</p>
            <p className="mb-4 text-sm">{error}</p>
            <Button onClick={fetchFlows} variant="destructive">
              Try Again
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="container mx-auto p-4 md:p-6 lg:p-8">
      <Card className="dark:bg-slate-800 dark:border-slate-700 shadow-lg">
        <CardHeader className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div>
            <CardTitle className="text-2xl font-semibold dark:text-slate-50">Conversation Flows</CardTitle>
            <CardDescription className="dark:text-slate-400">
              Manage your automated WhatsApp conversation flows.
            </CardDescription>
          </div>
          <Button onClick={handleCreateNewFlow} className="w-full md:w-auto bg-green-600 hover:bg-green-700 dark:bg-green-500 dark:hover:bg-green-600 text-white">
            <FiPlus className="mr-2 h-5 w-5" /> Create New Flow
          </Button>
        </CardHeader>
        <CardContent>
          {flows.length === 0 && !isLoading ? (
            <div className="text-center py-12 text-gray-500 dark:text-gray-400">
              <FiMessageCircle className="h-20 w-20 mx-auto mb-6 text-gray-400 dark:text-gray-500" />
              <p className="text-2xl font-semibold mb-3">No Flows Yet</p>
              <p className="mb-6">Get started by creating your first conversation flow.</p>
              <Button onClick={handleCreateNewFlow} size="lg" className="bg-green-600 hover:bg-green-700 dark:bg-green-500 dark:hover:bg-green-600 text-white">
                <FiPlus className="mr-2 h-5 w-5" /> Create Your First Flow
              </Button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700/30">
                    <TableHead className="dark:text-slate-300 w-[200px] sm:w-auto">Name</TableHead>
                    <TableHead className="dark:text-slate-300 min-w-[200px] hidden md:table-cell">Description</TableHead>
                    <TableHead className="dark:text-slate-300 text-center">Status</TableHead>
                    <TableHead className="dark:text-slate-300 hidden sm:table-cell">Triggers</TableHead>
                    <TableHead className="dark:text-slate-300 text-center hidden sm:table-cell">Steps</TableHead>
                    <TableHead className="text-right dark:text-slate-300 min-w-[240px] md:min-w-[280px]">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {flows.map((flow) => (
                    <TableRow key={flow.id} className="dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700/50">
                      <TableCell className="font-medium dark:text-slate-100 align-top py-3">
                        {flow.name}
                        <div className="text-xs text-slate-500 dark:text-slate-400 md:hidden mt-1 truncate max-w-[200px]" title={flow.description}>
                            {flow.description || <span className="italic">No description</span>}
                        </div>
                      </TableCell>
                      <TableCell className="text-sm text-gray-600 dark:text-slate-400 max-w-xs truncate hidden md:table-cell align-top py-3" title={flow.description}>
                        {flow.description || <span className="italic">No description</span>}
                      </TableCell>
                      <TableCell className="text-center align-top py-3">
                        <Badge
                          variant={flow.is_active ? 'default' : 'outline'}
                          className={`cursor-pointer ${flow.is_active
                            ? 'bg-green-100 text-green-700 border-green-300 hover:bg-green-200 dark:bg-green-700/30 dark:text-green-300 dark:border-green-600 dark:hover:bg-green-700/50'
                            : 'bg-gray-100 text-gray-600 border-gray-300 hover:bg-gray-200 dark:bg-slate-700 dark:text-slate-300 dark:border-slate-600 dark:hover:bg-slate-600/50'}`}
                          onClick={() => handleToggleFlowStatus(flow)}
                        >
                          {flow.is_active ? 'Active' : 'Inactive'}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs text-gray-500 dark:text-slate-400 hidden sm:table-cell align-top py-3">
                        {flow.trigger_keywords && flow.trigger_keywords.length > 0 ?
                          flow.trigger_keywords.slice(0, 2).join(', ') + (flow.trigger_keywords.length > 2 ? '...' : '') :
                          (flow.nlp_trigger_intent ? <span className="flex items-center gap-1"><FiZap className="text-purple-500"/> {flow.nlp_trigger_intent}</span> : <span className="italic">None</span>)
                        }
                      </TableCell>
                      <TableCell className="text-center dark:text-slate-300 hidden sm:table-cell align-top py-3">{flow.steps_count !== undefined ? flow.steps_count : 'N/A'}</TableCell>
                      <TableCell className="text-right space-x-1 align-top py-2">
                        <TooltipProvider delayDuration={300}>
                           <Tooltip>
                            <TooltipTrigger asChild>
                                <Button variant="ghost" size="icon" onClick={() => handleEditFlow(flow.id)} className="h-8 w-8 dark:text-slate-300 dark:hover:bg-slate-700">
                                    <FiEdit className="h-4 w-4 text-blue-500" />
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent><p>Edit Flow & Steps</p></TooltipContent>
                           </Tooltip>
                           <Tooltip>
                            <TooltipTrigger asChild>
                                <Button variant="ghost" size="icon" onClick={() => handleToggleFlowStatus(flow)} className="h-8 w-8 dark:text-slate-300 dark:hover:bg-slate-700">
                                    {flow.is_active ? <FiToggleRight className="h-5 w-5 text-green-500" /> : <FiToggleLeft className="h-5 w-5 text-slate-500" />}
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent><p>{flow.is_active ? 'Deactivate' : 'Activate'} Flow</p></TooltipContent>
                           </Tooltip>
                           <Tooltip>
                            <TooltipTrigger asChild>
                                <Button variant="ghost" size="icon" onClick={() => handleDeleteFlow(flow.id, flow.name)} className="h-8 w-8 text-red-500 hover:text-red-700 dark:hover:bg-red-900/30">
                                    <FiTrash2 className="h-4 w-4" />
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent><p>Delete Flow</p></TooltipContent>
                           </Tooltip>
                        </TooltipProvider>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
        {flows.length > 0 && (
            <CardFooter className="text-xs text-slate-500 dark:text-slate-400 pt-4 border-t dark:border-slate-700">
                <p>Total flows: {flows.length}</p>
                {/* TODO: Implement pagination controls here if your API supports it */}
            </CardFooter>
        )}
      </Card>
    </div>
  );
}