// src/components/bot_builder/TransitionEditorModal.jsx
import { Badge } from '../ui/badge';
import React, { useState, useEffect, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue, SelectGroup, SelectLabel
} from '@/components/ui/select';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter
} from "@/components/ui/dialog";
import { Card, CardContent } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { toast } from 'sonner';
import { FiPlus, FiEdit, FiTrash2, FiLoader, FiChevronsRight, FiGitBranch } from 'react-icons/fi';

export const CONDITION_TYPES = [
  { value: 'always_true', label: 'Always True (Unconditional)' },
  { value: 'user_reply_matches_keyword', label: 'User Reply IS Keyword' },
  { value: 'user_reply_contains_keyword', label: 'User Reply CONTAINS Keyword' },
  { value: 'interactive_reply_id_equals', label: 'Interactive Reply ID IS' },
  { value: 'variable_equals', label: 'Context Variable IS Value' },
  { value: 'user_reply_is_email', label: 'User Reply IS Email' },
  { value: 'user_reply_is_number', label: 'User Reply IS Number' },
  { value: 'user_reply_matches_regex', label: 'User Reply Matches Regex (UI TODO)' },
  { value: 'nfm_response_field_equals', label: 'NFM Response Field Equals (UI TODO)' },
  { value: 'question_reply_is_valid', label: 'Question Reply is Valid (UI TODO)' },
];

const initialConditionConfig = (type = 'always_true') => {
  const baseConfig = { type };
  switch (type) {
    case 'user_reply_matches_keyword':
    case 'user_reply_contains_keyword':
      baseConfig.keyword = '';
      baseConfig.case_sensitive = false;
      break;
    case 'interactive_reply_id_equals':
      baseConfig.reply_id = '';
      break;
    case 'variable_equals':
      baseConfig.variable_name = 'flow_context.your_variable';
      baseConfig.value = '';
      break;
    case 'user_reply_is_number':
      baseConfig.allow_decimal = false;
      baseConfig.min_value = null;
      baseConfig.max_value = null; // Corrected this from base_config to baseConfig
      break;
    default:
      break;
  }
  return baseConfig;
};

export default function TransitionEditorModal({
  isOpen,
  currentStep,
  allStepsInFlow,
  existingTransitions,
  editingTransitionState,
  onClose,
  onSave,
  onDelete,
  isLoadingExternally,
}) {
  const [editingTransition, setEditingTransitionInternal] = editingTransitionState;

  const [nextStepId, setNextStepId] = useState('');
  const [priority, setPriority] = useState(0);
  const [conditionConfig, setConditionConfig] = useState(initialConditionConfig());
  
  const [isSavingThisTransition, setIsSavingThisTransition] = useState(false);

  const resetFormForNew = useCallback(() => {
    setNextStepId('');
    const highestPriority = (existingTransitions || []).reduce((max, t) => Math.max(max, t.priority), -10);
    setPriority(highestPriority + 10);
    setConditionConfig(initialConditionConfig('always_true'));
  }, [existingTransitions]);

  useEffect(() => {
    if (editingTransition) {
      setNextStepId(editingTransition.next_step?.toString() || '');
      setPriority(editingTransition.priority !== undefined ? editingTransition.priority : 0);
      const conf = editingTransition.condition_config && typeof editingTransition.condition_config === 'object'
                   ? JSON.parse(JSON.stringify(editingTransition.condition_config)) 
                   : initialConditionConfig(editingTransition.condition_config?.type);
      setConditionConfig(conf);
    } else {
      resetFormForNew();
    }
  }, [editingTransition, resetFormForNew]);

  if (!isOpen || !currentStep) return null;

  const handleConfigValueChange = (field, value) => {
    setConditionConfig(prev => ({ ...prev, [field]: value }));
  };
  
  // ***** THIS IS THE FUNCTION DEFINITION *****
  const handleSelectedConditionTypeChange = (newType) => {
    setConditionConfig(initialConditionConfig(newType));
  };
  // *******************************************

  const handleFormSubmit = async (e) => {
    e.preventDefault();
    if (!nextStepId) {
      toast.error("Next step must be selected for the transition.");
      return;
    }
    setIsSavingThisTransition(true);
    const payload = {
      next_step: parseInt(nextStepId, 10),
      priority: parseInt(priority, 10) || 0,
      condition_config: conditionConfig, 
    };
    
    const isEditing = !!(editingTransition && editingTransition.id);
    const success = await onSave(isEditing, isEditing ? editingTransition.id : null, payload);
    
    setIsSavingThisTransition(false);
    if (success) {
      if (!isEditing) {
        resetFormForNew();
      } else {
        setEditingTransitionInternal(null); 
        resetFormForNew();
      }
    }
  };

  const startAddNewTransitionMode = () => {
    setEditingTransitionInternal(null); 
  };

  const renderConditionFields = () => {
    const currentCondType = conditionConfig.type || 'always_true';
    const conf = typeof conditionConfig === 'object' && conditionConfig !== null ? conditionConfig : {};

    switch (currentCondType) {
      case 'user_reply_matches_keyword':
      case 'user_reply_contains_keyword':
        return (
          <>
            <div className="space-y-1"><Label htmlFor="condKeyword">Keyword*</Label><Input id="condKeyword" value={conf.keyword || ''} onChange={(e) => handleConfigValueChange('keyword', e.target.value)} className="dark:bg-slate-700 dark:border-slate-600" /></div>
            <div className="flex items-center space-x-2 pt-2"><Switch id="condCaseSensitive" checked={conf.case_sensitive || false} onCheckedChange={(val) => handleConfigValueChange('case_sensitive', val)} className="data-[state=checked]:bg-blue-500" /><Label htmlFor="condCaseSensitive">Case Sensitive</Label></div>
          </>
        );
      case 'interactive_reply_id_equals':
        return <div className="space-y-1"><Label htmlFor="condReplyId">Expected Reply ID*</Label><Input id="condReplyId" value={conf.reply_id || ''} onChange={(e) => handleConfigValueChange('reply_id', e.target.value)} className="dark:bg-slate-700 dark:border-slate-600" /></div>;
      case 'variable_equals':
        return (
          <>
            <div className="space-y-1"><Label htmlFor="condVarName">Context Variable Path*</Label><Input id="condVarName" value={conf.variable_name || ''} onChange={(e) => handleConfigValueChange('variable_name', e.target.value)} placeholder="e.g., flow_context.user_email" className="dark:bg-slate-700 dark:border-slate-600" /></div>
            <div className="space-y-1"><Label htmlFor="condVarValue">Expected Value*</Label><Input id="condVarValue" value={conf.value !== undefined ? conf.value : ''} onChange={(e) => handleConfigValueChange('value', e.target.value)} placeholder="e.g., true or some_string" className="dark:bg-slate-700 dark:border-slate-600" /></div>
          </>
        );
       case 'user_reply_is_email':
        return <p className="text-sm text-slate-500 dark:text-slate-400">User's reply must be a valid email format.</p>;
       case 'user_reply_is_number':
        return (
            <div className="space-y-2">
                <div className="flex items-center space-x-2"><Switch id="condNumDecimal" checked={conf.allow_decimal || false} onCheckedChange={(val) => handleConfigValueChange('allow_decimal', val)} className="data-[state=checked]:bg-blue-500" /><Label htmlFor="condNumDecimal">Allow Decimal</Label></div>
                <div className="space-y-1"><Label htmlFor="condNumMin" className="text-xs">Min Value (optional)</Label><Input id="condNumMin" type="number" step="any" value={conf.min_value === null || conf.min_value === undefined ? '' : conf.min_value} onChange={(e) => handleConfigValueChange('min_value', e.target.value === '' ? null : parseFloat(e.target.value))} className="dark:bg-slate-700 dark:border-slate-600" /></div>
                <div className="space-y-1"><Label htmlFor="condNumMax" className="text-xs">Max Value (optional)</Label><Input id="condNumMax" type="number" step="any" value={conf.max_value === null || conf.max_value === undefined ? '' : conf.max_value} onChange={(e) => handleConfigValueChange('max_value', e.target.value === '' ? null : parseFloat(e.target.value))} className="dark:bg-slate-700 dark:border-slate-600" /></div>
            </div>
        );
      case 'always_true':
        return <p className="text-sm text-slate-500 dark:text-slate-400">This transition is unconditional (given its priority).</p>;
      default:
        return (
            <div className="space-y-1">
                <Label htmlFor="rawCondConfig" className="text-xs dark:text-slate-300">Other Condition Config (JSON for type: {currentCondType})</Label>
                <Textarea 
                    id="rawCondConfig" 
                    value={JSON.stringify(conditionConfig, null, 2)} 
                    onChange={(e) => {
                        try { 
                            const parsed = JSON.parse(e.target.value);
                            if (parsed.type !== currentCondType) parsed.type = currentCondType;
                            setConditionConfig(parsed);
                        } catch(err) { /* Allow invalid JSON during typing */ }
                    }}
                    rows={4} className="font-mono text-xs dark:bg-slate-700 dark:border-slate-600"/>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Edit JSON directly for this condition type.</p>
            </div>
        );
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open && !isSavingThisTransition) onClose(); else if (isSavingThisTransition) toast.info("Save in progress...") }}>
      <DialogContent className="sm:max-w-3xl md:max-w-4xl lg:max-w-5xl dark:bg-slate-800 dark:text-slate-50 h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="text-xl">Manage Transitions for Step: "<span className="font-semibold text-blue-500 dark:text-blue-400">{currentStep.name}</span>"</DialogTitle>
          <DialogDescription>Define how the flow proceeds from this step.</DialogDescription>
        </DialogHeader>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4 flex-grow overflow-hidden">
          {/* Left Column: List */}
          <div className="md:col-span-1 flex flex-col space-y-3 pr-3 md:border-r dark:border-slate-700 h-full">
            <div className="flex justify-between items-center mb-1 flex-shrink-0">
                <h3 className="text-lg font-medium dark:text-slate-200">Current Transitions ({existingTransitions.length})</h3>
                <Button size="sm" variant="outline" onClick={startAddNewTransitionMode} disabled={!editingTransition} className="dark:text-slate-300 dark:border-slate-600 dark:hover:bg-slate-700">
                    <FiPlus className="h-4 w-4 mr-1"/> Add New
                </Button>
            </div>
            {isLoadingExternally ? <div className="flex items-center justify-center p-4 h-full"><FiLoader className="animate-spin h-8 w-8" /></div> :
            existingTransitions.length === 0 ? <p className="text-sm text-slate-500 dark:text-slate-400 py-4 text-center h-full flex items-center justify-center">No transitions defined.</p> :
            <div className="flex-grow overflow-y-auto custom-scrollbar space-y-2 pr-1">
              {existingTransitions.sort((a,b) => a.priority - b.priority).map(t => (
                <Card key={t.id} className={`dark:bg-slate-700/70 dark:border-slate-600/80 hover:shadow-md transition-shadow ${editingTransition?.id === t.id ? 'ring-2 ring-blue-500 dark:ring-blue-400' : ''}`}>
                  <CardContent className="p-3 text-sm">
                    <div className="flex justify-between items-start gap-2">
                      <div className="flex-grow">
                          <p className="font-medium dark:text-slate-100 flex items-center text-base">
                              <FiChevronsRight className="mr-1.5 text-green-500 flex-shrink-0 h-5 w-5"/> To: {allStepsInFlow.find(s => s.id === t.next_step)?.name || `Step ID ${t.next_step}`}
                          </p>
                          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Priority: <Badge variant="secondary" className="px-1.5 py-0 text-xs dark:bg-slate-600 dark:text-slate-300">{t.priority}</Badge></p>
                          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">Condition: <span className="font-medium">{CONDITION_TYPES.find(ct => ct.value === t.condition_config?.type)?.label || t.condition_config?.type || 'Unknown'}</span></p>
                           {/* Display more condition details */}
                      </div>
                      <div className="flex flex-col space-y-1 flex-shrink-0 items-end">
                          <Button size="xs" variant="outline" onClick={() => setEditingTransitionInternal(t)} className="dark:text-slate-300 dark:border-slate-500 py-1 px-2 text-xs w-full justify-start"><FiEdit className="mr-1 h-3 w-3"/> Edit</Button>
                          <Button size="xs" variant="ghost" onClick={() => onDelete(t.id)} className="text-red-500 hover:text-red-700 hover:bg-red-100 dark:hover:bg-red-900/30 py-1 px-2 text-xs w-full justify-start"><FiTrash2 className="mr-1 h-3 w-3"/> Delete</Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
            }
          </div>

          {/* Right Column: Form */}
          <form onSubmit={handleFormSubmit} className="md:col-span-1 space-y-4 pl-0 md:pl-3 overflow-y-auto custom-scrollbar h-full pb-4">
            <h3 className="text-lg font-medium mb-1 dark:text-slate-200 flex items-center sticky top-0 bg-slate-800 py-2 z-10 border-b dark:border-slate-700 -ml-3 md:ml-0 pl-3 md:pl-0">
                {editingTransition ? <><FiEdit className="mr-2 h-5 w-5 text-blue-400"/>Edit Transition</> : <><FiPlus className="mr-2 h-5 w-5 text-green-400"/>Add New Transition</>}
            </h3>
            <div className="space-y-1">
              <Label htmlFor="nextStepForm" className="dark:text-slate-300">Next Step*</Label>
              <Select value={nextStepId.toString()} onValueChange={setNextStepId} disabled={isSavingThisTransition}>
                <SelectTrigger id="nextStepForm" className="dark:bg-slate-700 dark:border-slate-600"><SelectValue placeholder="Select next step..." /></SelectTrigger>
                <SelectContent className="dark:bg-slate-700 dark:text-slate-50">
                  <SelectGroup><SelectLabel className="dark:text-slate-400">Steps in "{currentStep.flow_name || 'this flow'}"</SelectLabel>
                    {allStepsInFlow.length === 0 && <SelectItem value="-" disabled>No other steps available</SelectItem>}
                    {allStepsInFlow.map(s => (<SelectItem key={s.id} value={s.id.toString()} className="dark:hover:bg-slate-600 dark:focus:bg-slate-600">{s.name}</SelectItem>))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="priorityForm" className="dark:text-slate-300">Priority (lower = higher priority)</Label>
              <Input id="priorityForm" type="number" value={priority} onChange={(e) => setPriority(parseInt(e.target.value, 10) || 0)} className="dark:bg-slate-700 dark:border-slate-600" disabled={isSavingThisTransition}/>
            </div>
            <Separator className="dark:bg-slate-600" />
            <Label className="dark:text-slate-300 font-medium block -mb-2">Condition</Label>
            <div className="space-y-1">
                <Label htmlFor="conditionTypeForm" className="text-xs dark:text-slate-300">Condition Type</Label>
                <Select value={conditionConfig.type || 'always_true'} onValueChange={handleSelectedConditionTypeChange} disabled={isSavingThisTransition}>
                    <SelectTrigger id="conditionTypeForm" className="dark:bg-slate-700 dark:border-slate-600"><SelectValue /></SelectTrigger>
                    <SelectContent className="dark:bg-slate-700 dark:text-slate-50">
                    {CONDITION_TYPES.map(ct => (<SelectItem key={ct.value} value={ct.value} className="dark:hover:bg-slate-600 dark:focus:bg-slate-600">{ct.label}</SelectItem>))}
                    </SelectContent>
                </Select>
            </div>
            <div className="pl-1 space-y-3 border-l-2 border-slate-700 ml-1 mt-2 pt-2 pb-1">
                {renderConditionFields()}
            </div>
            <div className="pt-3">
                <Button type="submit" disabled={isSavingThisTransition} className="w-full bg-blue-600 hover:bg-blue-700 text-white dark:bg-blue-500 dark:hover:bg-blue-600">
                {isSavingThisTransition ? <FiLoader className="animate-spin mr-2"/> : (editingTransition ? <FiSave className="mr-2"/> : <FiPlus className="mr-2"/>) }
                {editingTransition ? 'Update Transition' : 'Add Transition'}
                </Button>
            </div>
          </form>
        </div>

        <DialogFooter className="mt-auto pt-4 border-t dark:border-slate-700">
          <Button variant="outline" onClick={onClose} disabled={isSavingThisTransition} className="dark:text-slate-300 dark:border-slate-600">Done</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}