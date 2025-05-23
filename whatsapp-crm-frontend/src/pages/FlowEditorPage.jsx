// src/pages/FlowEditorPage.jsx
import React, { useState, useEffect, useCallback, useReducer } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';

// Shadcn/ui and other imports
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue, SelectGroup, SelectLabel } from '@/components/ui/select';
import { Dialog, DialogTrigger, DialogClose, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Separator } from '@/components/ui/separator';
import { Tooltip, TooltipProvider, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';

// Icons
import {
  FiSave, FiPlus, FiArrowLeft, FiSettings, FiGitBranch, FiLoader, FiAlertCircle, FiTrash2, FiChevronsRight, FiInfo
} from 'react-icons/fi';

// Notifications
import { toast } from 'sonner';

// Import your editor modals (ensure paths are correct)
import StepConfigEditor from '@/components/bot_builder/StepConfigEditor';
import TransitionEditorModal from '@/components/bot_builder/TransitionEditorModal';

// --- API Configuration & Helper ---
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const getAuthToken = () => localStorage.getItem('accessToken'); // Replace with your auth context/store

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
    if (response.status === 204 || (response.headers.get("content-length") || "0") === "0") return null;
    return await response.json();
  } catch (error) {
    console.error(`API call to ${method} ${API_BASE_URL}${endpoint} failed:`, error);
    toast.error(error.message || 'An API error occurred. Check console.'); throw error;
  }
}

// --- Constants ---
// Ensure this is consistent with your backend models.py and StepConfigEditor.jsx
export const STEP_TYPE_CHOICES = [
    { value: 'send_message', label: 'Send Message' }, 
    { value: 'question', label: 'Ask Question' },
    { value: 'action', label: 'Perform Action' }, 
    { value: 'start_flow_node', label: 'Start Node (Entry)' },
    { value: 'end_flow', label: 'End Flow' }, 
    { value: 'condition', label: 'Condition Node (Visual)' }, // If it's just visual, config might be minimal
    { value: 'human_handover', label: 'Handover to Human' },
];

const initialFlowDetailsState = {
  id: null, name: 'New Untitled Flow', description: '',
  triggerKeywordsRaw: '', nlpIntent: '', isActive: true,
};

// --- Reducers (keep as defined in message #69) ---
function stepsReducer(state, action) {
  const getDisplayType = (stepType) => STEP_TYPE_CHOICES.find(c => c.value === stepType)?.label || stepType;
  switch (action.type) {
    case 'SET_STEPS': return Array.isArray(action.payload) ? action.payload.map(s => ({...s, step_type_display: getDisplayType(s.step_type) })) : [];
    case 'ADD_STEP': return [...state, {...action.payload, step_type_display: getDisplayType(action.payload.step_type) }];
    case 'UPDATE_STEP': return state.map(step => step.id === action.payload.id ? { ...step, ...action.payload, step_type_display: getDisplayType(action.payload.step_type) } : step);
    case 'DELETE_STEP': return state.filter(step => step.id !== action.payload.id);
    default: throw new Error(`Unhandled stepsReducer action: ${action.type}`);
  }
}
function transitionsReducer(state, action) { /* ... same as message #69 ... */ 
  switch (action.type) {
    case 'SET_TRANSITIONS': return Array.isArray(action.payload) ? action.payload : [];
    case 'ADD_TRANSITION': return [...state, action.payload];
    case 'UPDATE_TRANSITION': return state.map(t => t.id === action.payload.id ? { ...t, ...action.payload } : t);
    case 'DELETE_TRANSITION': return state.filter(t => t.id !== action.payload.id);
    default: throw new Error(`Unhandled transitionsReducer action: ${action.type}`);
  }
}

// --- Main Component ---
export default function FlowEditorPage() {
  const { flowId: flowIdFromParams } = useParams();
  const navigate = useNavigate();
  const logger = console;

  const [flowDetails, setFlowDetails] = useState(initialFlowDetailsState);
  const [steps, dispatchSteps] = useReducer(stepsReducer, []);
  const [stepTransitions, dispatchStepTransitions] = useReducer(transitionsReducer, []);

  const [isLoading, setIsLoading] = useState(true);
  const [isSavingFlow, setIsSavingFlow] = useState(false);
  const [isOperatingOnStep, setIsOperatingOnStep] = useState(false);
  const [isLoadingTransitions, setIsLoadingTransitions] = useState(false);
  const [error, setError] = useState(null);

  const [showAddStepModal, setShowAddStepModal] = useState(false);
  const [newStepName, setNewStepName] = useState('');
  const [newStepType, setNewStepType] = useState(STEP_TYPE_CHOICES[0]?.value || 'send_message');
  
  const [editingStep, setEditingStep] = useState(null);
  const [managingTransitionsForStep, setManagingTransitionsForStep] = useState(null);
  const [editingTransition, setEditingTransition] = useState(null);

  // Fetch flow data
  useEffect(() => {
    const isNewFlow = !flowIdFromParams || flowIdFromParams === 'new';
    setFlowDetails(isNewFlow ? { ...initialFlowDetailsState, name: 'New Untitled Flow' } : initialFlowDetailsState);
    dispatchSteps({ type: 'SET_STEPS', payload: [] });
    dispatchStepTransitions({ type: 'SET_TRANSITIONS', payload: [] });
    setEditingStep(null); setManagingTransitionsForStep(null); setEditingTransition(null);

    if (!isNewFlow) {
      setIsLoading(true);
      const loadFullFlowData = async () => {
        try {
          logger.info(`Loading flow data for ID: ${flowIdFromParams}`);
          const fetchedFlow = await apiCall(`/crm-api/flows/flows/${flowIdFromParams}/`);
          setFlowDetails({
            id: fetchedFlow.id, name: fetchedFlow.name || '', description: fetchedFlow.description || '',
            triggerKeywordsRaw: (fetchedFlow.trigger_keywords || []).join(', '),
            nlpIntent: fetchedFlow.nlp_trigger_intent || '',
            isActive: fetchedFlow.is_active !== undefined ? fetchedFlow.is_active : true,
          });

          const fetchedSteps = await apiCall(`/crm-api/flows/flows/${flowIdFromParams}/steps/`);
          dispatchSteps({ type: 'SET_STEPS', payload: (fetchedSteps.results || fetchedSteps || []) });
          setError(null);
        } catch (err) { setError(err.message); setFlowDetails(prev => ({...prev, name: "Error Loading Flow Data"})); }
        finally { setIsLoading(false); }
      };
      loadFullFlowData();
    } else {
      logger.info("Initializing for new flow creation.");
      setIsLoading(false);
    }
  }, [flowIdFromParams, logger]);

  const handleFlowDetailChange = (field, value) => setFlowDetails(prev => ({ ...prev, [field]: value }));

  const handleSaveFlowDetails = async () => {
    if (!flowDetails.name.trim()) { toast.error("Flow name is required."); return; }
    setIsSavingFlow(true); setError(null);
    const isNewFlowCreation = !flowDetails.id;
    const payload = {
      name: flowDetails.name, description: flowDetails.description, is_active: flowDetails.isActive,
      trigger_keywords: flowDetails.triggerKeywordsRaw.split(',').map(k => k.trim()).filter(k => k),
      nlp_trigger_intent: flowDetails.nlpIntent || null,
    };
    try {
      let savedFlowData;
      if (isNewFlowCreation) {
        savedFlowData = await apiCall('/crm-api/flows/flows/', 'POST', payload);
        toast.success(`Flow "${savedFlowData.name}" created successfully!`);
        setFlowDetails(prev => ({...prev, id: savedFlowData.id, ...savedFlowData}));
        navigate(`/flows/edit/${savedFlowData.id}`, { replace: true });
      } else {
        savedFlowData = await apiCall(`/crm-api/flows/flows/${flowDetails.id}/`, 'PUT', payload);
        toast.success(`Flow "${savedFlowData.name}" details updated!`);
        setFlowDetails(prev => ({...prev, ...savedFlowData}));
      }
    } catch (err) { setError(err.message); }
    finally { setIsSavingFlow(false); }
  };

  const handleAddNewStep = async () => {
    if (!newStepName.trim() || !newStepType) { toast.error("Step name and type are required."); return; }
    if (!flowDetails.id) { toast.error("Save the Flow first before adding steps."); return; }
    setIsOperatingOnStep(true);
    let initialConfig = {};
    if (newStepType === 'send_message') initialConfig = { message_type: 'text', text: { body: '' } };
    else if (newStepType === 'question') initialConfig = { message_config: { message_type: 'text', text: { body: '' }}, reply_config: { save_to_variable: 'user_answer', expected_type: 'text'} };
    else if (newStepType === 'action') initialConfig = { actions_to_run: [] };
    else if (newStepType === 'start_flow_node') initialConfig = { note: "Flow Entry Point" };
    else if (newStepType === 'end_flow') initialConfig = { note: "Flow End Point" };
    else initialConfig = { }; // Default for condition, etc.

    const newStepPayload = {
      flow: flowDetails.id, name: newStepName, step_type: newStepType, config: initialConfig,
      is_entry_point: !steps.some(s => s.is_entry_point),
    };
    try {
      const createdStep = await apiCall(`/crm-api/flows/flows/${flowDetails.id}/steps/`, 'POST', newStepPayload);
      dispatchSteps({ type: 'ADD_STEP', payload: createdStep });
      toast.success(`Step "${createdStep.name}" added.`);
      setNewStepName(''); setNewStepType(STEP_TYPE_CHOICES[0]?.value); setShowAddStepModal(false);
    } catch (err) { logger.error("Error adding new step:", err.data || err.message); }
    finally { setIsOperatingOnStep(false); }
  };
  
  const handleOpenEditStepModal = (stepToEdit) => setEditingStep(stepToEdit);

  const handleSaveEditedStep = async (stepId, updatedStepDataFromModal) => {
    if (!flowDetails.id) { toast.error("Flow ID is missing."); return false; }
    // No need to set isOperatingOnStep here, StepConfigEditor has its own isSavingStep
    let success = false;
    try {
        const patchedStep = await apiCall(`/crm-api/flows/flows/${flowDetails.id}/steps/${stepId}/`, 'PATCH', updatedStepDataFromModal);
        dispatchSteps({ type: 'UPDATE_STEP', payload: patchedStep });
        toast.success(`Step "${patchedStep.name}" updated.`);
        success = true;
    } catch (err) {
        if (err.data && typeof err.data === 'object') {
            Object.entries(err.data).forEach(([field, messages]) => {
                toast.error(`${field.replace(/_/g, " ")}: ${Array.isArray(messages) ? messages.join(', ') : messages}`);
            });
        } success = false;
    }
    return success;
  };

  const handleDeleteStep = async (stepId, stepName) => {
    if (!window.confirm(`Delete step "${stepName}" and its transitions?`)) return;
    if (!flowDetails.id) return;
    setIsOperatingOnStep(true);
    try {
      await apiCall(`/crm-api/flows/flows/${flowDetails.id}/steps/${stepId}/`, 'DELETE');
      dispatchSteps({ type: 'DELETE_STEP', payload: { id: stepId } });
      toast.success(`Step "${stepName}" deleted.`);
      if (editingStep?.id === stepId) setEditingStep(null);
      if (managingTransitionsForStep?.id === stepId) setManagingTransitionsForStep(null);
    } catch (err) { /* toast handled by apiCall */ }
    finally { setIsOperatingOnStep(false); }
  };

  const handleOpenManageTransitions = async (step) => {
    if (!flowDetails.id || !step?.id) { toast.error("Flow/Step info missing."); return; }
    setManagingTransitionsForStep(step); setEditingTransition(null); setIsLoadingTransitions(true);
    try {
      const fetchedTransitions = await apiCall(`/crm-api/flows/flows/${flowDetails.id}/steps/${step.id}/transitions/`);
      dispatchStepTransitions({ type: 'SET_TRANSITIONS', payload: (fetchedTransitions.results || fetchedTransitions || []) });
    } catch (err) { dispatchStepTransitions({ type: 'SET_TRANSITIONS', payload: [] }); }
    finally { setIsLoadingTransitions(false); }
  };

  const handleSaveTransition = async (isEditingMode, transitionIdToUpdate, transitionDataFromModal) => {
    if (!managingTransitionsForStep?.id || !flowDetails.id) { toast.error("Context missing for saving transition."); return false; }
    const currentStepId = managingTransitionsForStep.id;
    let success = false;
    try {
      let savedTransition;
      const payload = { ...transitionDataFromModal };
      if (!isEditingMode) payload.current_step = currentStepId; 
      const endpoint = isEditingMode
        ? `/crm-api/flows/flows/${flowDetails.id}/steps/${currentStepId}/transitions/${transitionIdToUpdate}/`
        : `/crm-api/flows/flows/${flowDetails.id}/steps/${currentStepId}/transitions/`;
      const method = isEditingMode ? 'PUT' : 'POST';
      savedTransition = await apiCall(endpoint, method, payload);
      if (isEditingMode) {
        dispatchStepTransitions({ type: 'UPDATE_TRANSITION', payload: savedTransition });
        toast.success("Transition updated!");
      } else {
        dispatchStepTransitions({ type: 'ADD_TRANSITION', payload: savedTransition });
        toast.success("Transition added!");
      }
      success = true;
    } catch (err) {
      if (err.data && typeof err.data === 'object') {
          Object.entries(err.data).forEach(([field, messages]) => {
              toast.error(`${field.replace(/_/g, " ")}: ${Array.isArray(messages) ? messages.join(', ') : messages}`);
          });
      } success = false;
    }
    return success;
  };

  const handleDeleteTransition = async (transitionIdToDelete) => {
    if (!managingTransitionsForStep?.id || !flowDetails.id || !transitionIdToDelete) return;
    if (!window.confirm("Delete this transition?")) return;
    const currentStepId = managingTransitionsForStep.id;
    try {
      await apiCall(`/crm-api/flows/flows/${flowDetails.id}/steps/${currentStepId}/transitions/${transitionIdToDelete}/`, 'DELETE');
      dispatchStepTransitions({ type: 'DELETE_TRANSITION', payload: { id: transitionIdToDelete } });
      toast.success("Transition deleted.");
      if (editingTransition?.id === transitionIdToDelete) setEditingTransition(null);
    } catch (err) { /* toast handled */ }
  };

  // --- RENDER LOGIC ---
  if (isLoading) return <div className="flex items-center justify-center h-screen"><FiLoader className="animate-spin h-16 w-16 text-blue-600 dark:text-blue-300" /> <p className="ml-4 text-2xl dark:text-slate-300">Loading Flow Editor...</p></div>;
  if (error && !flowDetails.id && flowIdFromParams && flowIdFromParams !== 'new') {
    return (
      <div className="container mx-auto p-8 text-center">
        <Card className="max-w-md mx-auto border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-900/10">
          <CardContent className="p-8"><FiAlertCircle size={56} className="mx-auto mb-4 text-red-500 dark:text-red-600"/><h2 className="text-2xl font-semibold text-red-700 dark:text-red-400 mb-3">Error Loading Flow</h2><p className="mb-6 text-red-600 dark:text-red-500 text-sm">{error}</p><Button variant="outline" onClick={() => navigate('/flows')} className="dark:text-slate-300 dark:border-slate-600"><FiArrowLeft className="mr-2"/> Back to Flows List</Button></CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="container mx-auto p-4 md:p-6 space-y-6 mb-20">
      {/* Header */}
      <div className="flex flex-wrap justify-between items-center gap-4 pb-4 border-b dark:border-slate-700">
        <div className="flex items-center gap-3 flex-grow min-w-0">
            <TooltipProvider><Tooltip><TooltipTrigger asChild>
                <Button variant="outline" size="icon" onClick={() => navigate('/flows')} className="dark:text-slate-300 dark:border-slate-600 h-10 w-10 flex-shrink-0"><FiArrowLeft className="h-5 w-5" /></Button>
            </TooltipTrigger><TooltipContent><p>Back to Flows List</p></TooltipContent></Tooltip></TooltipProvider>
            <div className="flex-grow min-w-0">
                <Input id="flowPageName" value={flowDetails.name} onChange={(e) => handleFlowDetailChange('name', e.target.value)} className="text-xl sm:text-2xl md:text-3xl font-bold dark:text-slate-50 dark:bg-transparent border-0 border-b-2 border-transparent focus:border-blue-500 dark:focus:border-blue-400 focus:ring-0 h-auto p-0 truncate" placeholder="Flow Name"/>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">ID: {flowDetails.id || "Unsaved"}</p>
            </div>
        </div>
        <Button onClick={handleSaveFlowDetails} disabled={isSavingFlow || isLoading} className="bg-green-600 hover:bg-green-700 text-white dark:bg-green-500 dark:hover:bg-green-600 min-w-[140px] h-10 flex-shrink-0">
          {isSavingFlow ? <FiLoader className="animate-spin mr-2" /> : <FiSave className="mr-2 h-4 w-4" />}
          {isSavingFlow ? 'Saving...' : (flowDetails.id ? 'Save Flow Details' : 'Create & Save Flow')}
        </Button>
      </div>

      {/* Flow Metadata Card */}
      <Card className="dark:bg-slate-800 dark:border-slate-700">
        <CardHeader>
            <CardTitle className="dark:text-slate-100 text-lg flex items-center gap-2"><FiSettings/> Flow Configuration</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4">
          <div className="md:col-span-2 space-y-1"><Label htmlFor="flowDesc" className="dark:text-slate-300">Description</Label><Textarea id="flowDesc" value={flowDetails.description} onChange={(e) => handleFlowDetailChange('description', e.target.value)} rows={2} className="dark:bg-slate-700 dark:border-slate-600 dark:text-slate-100" placeholder="A brief summary of what this flow achieves."/></div>
          <div className="space-y-1"><Label htmlFor="triggerKeywords" className="dark:text-slate-300">Trigger Keywords (comma-separated)</Label><Input id="triggerKeywords" value={flowDetails.triggerKeywordsRaw} onChange={(e) => handleFlowDetailChange('triggerKeywordsRaw', e.target.value)} className="dark:bg-slate-700 dark:border-slate-600 dark:text-slate-100" placeholder="e.g., hi, start, menu"/></div>
          <div className="space-y-1"><Label htmlFor="nlpIntent" className="dark:text-slate-300">NLP Trigger Intent (Optional)</Label><Input id="nlpIntent" value={flowDetails.nlpIntent} onChange={(e) => handleFlowDetailChange('nlpIntent', e.target.value)} className="dark:bg-slate-700 dark:border-slate-600 dark:text-slate-100" placeholder="e.g., UserRequestQuote"/></div>
          <div className="flex items-center space-x-2 md:col-span-2 pt-3">
            <Switch id="isActive" checked={flowDetails.isActive} onCheckedChange={(val) => handleFlowDetailChange('isActive', val)} className="data-[state=checked]:bg-green-500"/>
            <Label htmlFor="isActive" className="dark:text-slate-300 cursor-pointer">Flow is Active</Label>
            <TooltipProvider delayDuration={100}><Tooltip>
                <TooltipTrigger type="button" className="ml-1 text-slate-400 dark:text-slate-500"><FiInfo size={14}/></TooltipTrigger>
                <TooltipContent><p className="text-xs max-w-xs">Active flows can be triggered by users. Inactive flows are saved but not live.</p></TooltipContent>
            </Tooltip></TooltipProvider>
          </div>
        </CardContent>
      </Card>

      {/* Flow Steps Management Card */}
      {flowDetails.id && ( // Only show steps if flow is saved and has an ID
        <Card className="dark:bg-slate-800 dark:border-slate-700">
          <CardHeader className="flex flex-row items-center justify-between">
            <div><CardTitle className="dark:text-slate-100 text-lg">Flow Steps</CardTitle><CardDescription className="dark:text-slate-400">Define the sequence of messages, questions, and actions for this flow.</CardDescription></div>
            <Dialog open={showAddStepModal} onOpenChange={setShowAddStepModal}>
              <DialogTrigger asChild><Button variant="outline" className="dark:text-slate-300 dark:border-slate-600 dark:hover:bg-slate-700"><FiPlus className="mr-2 h-4 w-4" /> Add Step</Button></DialogTrigger>
              <DialogContent className="sm:max-w-md dark:bg-slate-800 dark:text-slate-50">
                <DialogHeader><DialogTitle>Add New Step to "{flowDetails.name}"</DialogTitle></DialogHeader>
                <div className="grid gap-4 py-4">
                  <div className="space-y-1"><Label htmlFor="newStepName" className="dark:text-slate-300">Step Name*</Label><Input id="newStepName" value={newStepName} onChange={(e) => setNewStepName(e.target.value)} className="dark:bg-slate-700 dark:border-slate-600"/></div>
                  <div className="space-y-1"><Label htmlFor="newStepType" className="dark:text-slate-300">Step Type*</Label>
                    <Select value={newStepType} onValueChange={setNewStepType}>
                      <SelectTrigger className="dark:bg-slate-700 dark:border-slate-600"><SelectValue placeholder="Select type" /></SelectTrigger>
                      <SelectContent className="dark:bg-slate-700 dark:text-slate-50">{STEP_TYPE_CHOICES.map(c => <SelectItem key={c.value} value={c.value} className="dark:hover:bg-slate-600 dark:focus:bg-slate-600">{c.label}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                </div>
                <DialogFooter>
                  <DialogClose asChild><Button variant="outline" className="dark:text-slate-300 dark:border-slate-600">Cancel</Button></DialogClose>
                  <Button onClick={handleAddNewStep} disabled={isOperatingOnStep} className="bg-blue-600 hover:bg-blue-700 text-white">
                    {isOperatingOnStep ? <FiLoader className="animate-spin"/> : "Add Step"}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </CardHeader>
          <CardContent>
            {steps.length === 0 ? <p className="text-slate-500 dark:text-slate-400 text-center py-6">This flow has no steps yet. Click "Add Step" to begin building the conversation path!</p> : (
              <div className="space-y-3">
                {/* TODO: Consider a drag-and-drop library for reordering steps visually */}
                {steps.map((step) => (
                  <Card key={step.id} className="dark:bg-slate-700/60 dark:border-slate-600/80 hover:shadow-md transition-shadow">
                    <CardHeader className="flex flex-col sm:flex-row justify-between sm:items-center p-3 gap-2">
                        <div className="flex-grow min-w-0">
                            <h4 className="font-medium dark:text-slate-100 truncate" title={step.name}>{step.name}</h4>
                            <p className="text-xs text-slate-400 dark:text-slate-400 flex items-center gap-2">
                                Type: {step.step_type_display || step.step_type} {/* Use step_type_display from reducer */}
                                {step.is_entry_point && <Badge variant="outline" className="border-green-400 text-green-500 dark:text-green-300 text-xs px-1.5 py-0.5 ml-2">Entry Point</Badge>}
                            </p>
                        </div>
                        <div className="space-x-1 flex-shrink-0 self-start sm:self-center mt-2 sm:mt-0">
                            <TooltipProvider delayDuration={200}>
                                <Tooltip><TooltipTrigger asChild><Button variant="ghost" size="icon" onClick={() => handleOpenEditStepModal(step)} className="h-8 w-8 dark:text-slate-300 dark:hover:bg-slate-600"><FiSettings className="h-4 w-4 text-blue-400" /></Button></TooltipTrigger><TooltipContent><p>Configure Step</p></TooltipContent></Tooltip>
                                <Tooltip><TooltipTrigger asChild><Button variant="ghost" size="icon" onClick={() => handleOpenManageTransitions(step)} className="h-8 w-8 dark:text-slate-300 dark:hover:bg-slate-600"><FiGitBranch className="h-4 w-4 text-purple-400" /></Button></TooltipTrigger><TooltipContent><p>Manage Transitions</p></TooltipContent></Tooltip>
                                <Tooltip><TooltipTrigger asChild><Button variant="ghost" size="icon" onClick={() => handleDeleteStep(step.id, step.name)} className="h-8 w-8 text-red-500 hover:text-red-700 dark:hover:bg-red-900/40"><FiTrash2 className="h-4 w-4" /></Button></TooltipTrigger><TooltipContent><p>Delete Step</p></TooltipContent></Tooltip>
                            </TooltipProvider>
                        </div>
                    </CardHeader>
                  </Card>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Modals are rendered here, controlled by their respective state variables */}
      {editingStep && (
        <StepConfigEditor
          key={`step-config-${editingStep.id}`} // Force re-mount on step change
          isOpen={!!editingStep}
          step={editingStep}
          onClose={() => setEditingStep(null)}
          onSaveStep={handleSaveEditedStep} // This function makes the API call
        />
      )}

      {managingTransitionsForStep && (
        <TransitionEditorModal
          key={`trans-manage-${managingTransitionsForStep.id}`} // Force re-mount
          isOpen={!!managingTransitionsForStep}
          currentStep={managingTransitionsForStep}
          // Pass steps from the current flow, excluding the current step itself.
          // Ensure flowDetails.id is valid and steps are loaded before filtering.
          allStepsInFlow={flowDetails.id ? steps.filter(s => s.flow === flowDetails.id && s.id !== managingTransitionsForStep.id) : []}
          existingTransitions={stepTransitions} // These are transitions for the currentStep
          editingTransitionState={[editingTransition, setEditingTransition]}
          onClose={() => {
            setManagingTransitionsForStep(null);
            setEditingTransition(null);
            dispatchStepTransitions({ type: 'SET_TRANSITIONS', payload: [] }); // Clear when modal closes
          }}
          onSave={handleSaveTransition} // Expects (isEditing, transitionId, payload)
          onDelete={handleDeleteTransition} // Expects (transitionId)
          isLoadingExternally={isLoadingTransitions}
        />
      )}
    </div>
  );
}