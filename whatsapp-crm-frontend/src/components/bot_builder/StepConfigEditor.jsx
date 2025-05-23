// src/components/bot_builder/StepConfigEditor.jsx
import React, { useState, useEffect, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter
} from "@/components/ui/dialog";
import { Separator } from '@/components/ui/separator';
import { toast } from 'sonner';
import { FiLoader, FiSave, FiPlusCircle, FiTrash2 } from 'react-icons/fi';
import MediaAssetSelector from './MediaAssetSelector'; // Ensure this component is created/imported

// Message Types available for 'send_message' steps config.message_config.message_type
const MESSAGE_CONFIG_TYPES = [
    { value: 'text', label: 'Text Message' },
    { value: 'image', label: 'Image (from Media Library)' },
    { value: 'document', label: 'Document (from Media Library)' },
    { value: 'interactive', label: 'Interactive Message' }, // Parent type for buttons/lists
    { value: 'template', label: 'Template Message (UI TODO)' },
    { value: 'video', label: 'Video (from Media Library) (UI TODO)' },
    { value: 'audio', label: 'Audio (from Media Library) (UI TODO)' },
    { value: 'sticker', label: 'Sticker (from Media Library) (UI TODO)' },
];

// Interactive Message subtypes (for config.message_config.interactive.type)
const INTERACTIVE_MESSAGE_SUBTYPES = [
    { value: 'button', label: 'Reply Buttons' },
    { value: 'list', label: 'List Message (UI TODO)' },
    // { value: 'product', label: 'Single Product Message (UI TODO)' },
    // { value: 'product_list', label: 'Multi-Product Message (UI TODO)' },
];

// Action Types available for 'action' steps (config.actions_to_run[n].action_type)
const ACTION_CONFIG_TYPES = [
    { value: 'set_context_variable', label: 'Set Context Variable' },
    { value: 'update_contact_field', label: 'Update Contact Field (UI TODO)' },
    { value: 'update_customer_profile', label: 'Update Customer Profile (UI TODO)' },
];

export default function StepConfigEditor({ isOpen, step, onClose, onSaveStep }) {
  const [stepName, setStepName] = useState('');
  const [isEntryPoint, setIsEntryPoint] = useState(false);
  const [currentConfig, setCurrentConfig] = useState({}); // Main config object for the step
  const [isSavingStep, setIsSavingStep] = useState(false);
  
  // Specific state for complex nested parts, like interactive buttons
  const [interactiveButtons, setInteractiveButtons] = useState([]);

  // Initialize/Reset internal state when 'step' prop changes
  useEffect(() => {
    if (step) {
      setStepName(step.name || '');
      setIsEntryPoint(step.is_entry_point || false);
      const initialConfig = step.config ? JSON.parse(JSON.stringify(step.config)) : {};
      setCurrentConfig(initialConfig);

      // Initialize interactiveButtons state if the step is send_message and interactive_button
      if (step.step_type === 'send_message' &&
          initialConfig.message_config?.message_type === 'interactive' &&
          initialConfig.message_config?.interactive?.type === 'button') {
        setInteractiveButtons(initialConfig.message_config.interactive.action?.buttons || []);
      } else {
        setInteractiveButtons([]);
      }
    } else { // Reset when no step (modal closes or new step before first save)
      setStepName('');
      setIsEntryPoint(false);
      setCurrentConfig({});
      setInteractiveButtons([]);
    }
  }, [step]);

  if (!isOpen || !step) {
    return null;
  }

  // Helper to update nested properties in currentConfig
  const handleConfigPathChange = (path, value) => {
    setCurrentConfig(prevConfig => {
      const newConfig = JSON.parse(JSON.stringify(prevConfig)); // Deep clone
      let currentLevel = newConfig;
      const keys = path.split('.');
      keys.forEach((key, index) => {
        const isLastKey = index === keys.length - 1;
        const isNextKeyNumeric = !isLastKey && /^\d+$/.test(keys[index + 1]);

        if (isLastKey) {
          currentLevel[key] = value;
        } else {
          if (!currentLevel[key] || typeof currentLevel[key] !== 'object') {
            currentLevel[key] = isNextKeyNumeric ? [] : {};
          }
          currentLevel = currentLevel[key];
        }
      });
      return newConfig;
    });
  };
  
  // For top-level raw JSON editing of the whole config
  const handleRawConfigChange = (jsonString) => {
    try {
        const parsed = JSON.parse(jsonString);
        setCurrentConfig(parsed);
        // If send_message and interactive button, re-sync interactiveButtons state
        if (step.step_type === 'send_message' &&
            parsed.message_config?.message_type === 'interactive' &&
            parsed.message_config?.interactive?.type === 'button') {
            setInteractiveButtons(parsed.message_config.interactive.action?.buttons || []);
        }
    } catch (e) {
        setCurrentConfig(jsonString); // Store as string if not valid JSON, for user to fix
        toast.error("Config JSON is invalid. Please correct it.", {id: `json-err-${step.id}`, duration: 2000});
    }
  };

  const handleSave = async () => {
    if (!stepName.trim()) { toast.error("Step name cannot be empty."); return; }
    setIsSavingStep(true);
    let finalConfig = currentConfig;

    if (typeof currentConfig === 'string') {
        try { finalConfig = JSON.parse(currentConfig); }
        catch (e) { toast.error("Configuration JSON is invalid. Correct before saving."); setIsSavingStep(false); return; }
    }

    // Ensure interactive buttons are correctly structured in finalConfig
    if (step.step_type === 'send_message' &&
        finalConfig.message_config?.message_type === 'interactive' &&
        finalConfig.message_config?.interactive?.type === 'button') {
        
        finalConfig.message_config.interactive.action = {
            ...(finalConfig.message_config.interactive.action || {}),
            buttons: interactiveButtons.map(btn => ({ // Ensure buttons have 'type':'reply'
                type: 'reply',
                reply: { id: btn.reply?.id || '', title: btn.reply?.title || '' }
            }))
        };
    }

    const payload = { name: stepName, is_entry_point: isEntryPoint, config: finalConfig };
    const success = await onSaveStep(step.id, payload); // onSaveStep is passed from FlowEditorPage
    setIsSavingStep(false);
    if (success) onClose();
  };

  // --- UI Renderers for different config types ---

  // Specific to step_type: 'send_message'
  const renderSendMessageConfig = () => {
    const msgConf = currentConfig.message_config || {}; // All message configs are under "message_config"
    const currentMsgType = msgConf.message_type || 'text';

    return (
      <div className="space-y-4 p-2 border dark:border-slate-700 rounded-md mt-2">
        <div className="space-y-1 p-3">
          <Label htmlFor="messageConfigTypeSelect" className="dark:text-slate-300">Message Content Type</Label>
          <Select
            value={currentMsgType}
            onValueChange={(val) => {
              const newMsgConf = { message_type: val };
              if (val === 'text') newMsgConf.text = { body: '', preview_url: false };
              else if (val === 'image') newMsgConf.image = { asset_pk: null, caption: '' };
              else if (val === 'document') newMsgConf.document = { asset_pk: null, caption: '', filename: '' };
              else if (val === 'interactive') { // Default interactive to 'button' subtype
                newMsgConf.interactive = { type: 'button', body: { text: '' }, action: { buttons: [] }};
                setInteractiveButtons([]);
              }
              // TODO: Add specific initial configs for other types (video, audio, template, list)
              handleConfigPathChange('message_config', newMsgConf);
            }}
          >
            <SelectTrigger id="messageConfigTypeSelect" className="dark:bg-slate-700 dark:border-slate-600"><SelectValue /></SelectTrigger>
            <SelectContent className="dark:bg-slate-700 dark:text-slate-50">
              {MESSAGE_CONFIG_TYPES.map(mt => <SelectItem key={mt.value} value={mt.value} className="dark:hover:bg-slate-600">{mt.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>

        {currentMsgType === 'text' && (
          <div className="space-y-2 p-3 border-t dark:border-slate-700">
            <Label htmlFor="textBody" className="dark:text-slate-300">Body*</Label>
            <Textarea id="textBody" value={msgConf.text?.body || ''} onChange={(e) => handleConfigPathChange('message_config.text.body', e.target.value)} rows={4} className="dark:bg-slate-700 dark:border-slate-600" placeholder="Hello {{ contact.name }}!"/>
            <div className="flex items-center space-x-2 pt-1">
              <Switch id="textPreviewUrl" checked={msgConf.text?.preview_url || false} onCheckedChange={(val) => handleConfigPathChange('message_config.text.preview_url', val)} className="data-[state=checked]:bg-green-500"/>
              <Label htmlFor="textPreviewUrl" className="text-xs dark:text-slate-300">Enable Link Preview</Label>
            </div>
          </div>
        )}

        {(currentMsgType === 'image' || currentMsgType === 'document' || currentMsgType === 'video' || currentMsgType === 'audio' || currentMsgType === 'sticker') && (
          <div className="space-y-2 p-3 border-t dark:border-slate-700">
            {!['image', 'document'].includes(currentMsgType) && <p className="text-sm text-amber-500 dark:text-amber-400">UI for {currentMsgType} selection is a TODO. Use Raw JSON if needed.</p>}
            {(['image', 'document'].includes(currentMsgType)) && (
                <>
                    <Label className="dark:text-slate-300">{currentMsgType.charAt(0).toUpperCase() + currentMsgType.slice(1)} Asset*</Label>
                    <MediaAssetSelector
                        currentAssetPk={msgConf[currentMsgType]?.asset_pk || null}
                        mediaTypeFilter={currentMsgType}
                        onAssetSelect={(assetPk) => handleConfigPathChange(`message_config.${currentMsgType}.asset_pk`, assetPk)}
                    />
                </>
            )}
            {currentMsgType === 'document' && (
                <div className="space-y-1 mt-2">
                    <Label htmlFor={`${currentMsgType}Filename`} className="text-xs dark:text-slate-300">Filename (Optional, e.g., report.pdf)</Label>
                    <Input id={`${currentMsgType}Filename`} value={msgConf[currentMsgType]?.filename || ''} onChange={(e) => handleConfigPathChange(`message_config.${currentMsgType}.filename`, e.target.value)} className="dark:bg-slate-700 dark:border-slate-600"/>
                </div>
            )}
            {(currentMsgType === 'image' || currentMsgType === 'document' || currentMsgType === 'video') && (
                <div className="space-y-1 mt-2">
                    <Label htmlFor={`${currentMsgType}Caption`} className="text-xs dark:text-slate-300">Caption (Optional)</Label>
                    <Textarea id={`${currentMsgType}Caption`} value={msgConf[currentMsgType]?.caption || ''} onChange={(e) => handleConfigPathChange(`message_config.${currentMsgType}.caption`, e.target.value)} rows={2} className="dark:bg-slate-700 dark:border-slate-600"/>
                </div>
            )}
          </div>
        )}
        
        {currentMsgType === 'interactive' && (
            <div className="space-y-3 p-3 border-t dark:border-slate-700">
                <Label className="dark:text-slate-300">Interactive Message Sub-Type</Label>
                 <Select
                    value={msgConf.interactive?.type || 'button'}
                    onValueChange={(val) => {
                        const newInteractiveConf = { type: val };
                        if (val === 'button') {
                             newInteractiveConf.body = { text: msgConf.interactive?.body?.text || '' };
                             newInteractiveConf.action = { buttons: [] };
                             setInteractiveButtons([]); // Reset local button state
                        }
                        // TODO: Add resets for 'list' type
                        handleConfigPathChange('message_config.interactive', newInteractiveConf);
                    }}
                >
                    <SelectTrigger className="dark:bg-slate-700 dark:border-slate-600"><SelectValue /></SelectTrigger>
                    <SelectContent className="dark:bg-slate-700 dark:text-slate-50">
                        {INTERACTIVE_MESSAGE_SUBTYPES.map(subt => <SelectItem key={subt.value} value={subt.value} disabled={subt.value === 'list'} className="dark:hover:bg-slate-600">{subt.label}</SelectItem>)}
                    </SelectContent>
                </Select>

                {msgConf.interactive?.type === 'button' && (
                    <div className="space-y-2 mt-2">
                        <div className="space-y-1"><Label htmlFor="interactiveBodyText" className="text-xs">Body Text*</Label><Textarea id="interactiveBodyText" value={msgConf.interactive?.body?.text || ''} onChange={(e) => handleConfigPathChange('message_config.interactive.body.text', e.target.value)} rows={2} className="dark:bg-slate-700 dark:border-slate-600"/></div>
                        <div className="space-y-1"><Label htmlFor="interactiveHeaderText" className="text-xs">Header Text (Optional)</Label><Input id="interactiveHeaderText" value={msgConf.interactive?.header?.text || ''} onChange={(e) => handleConfigPathChange('message_config.interactive.header.text', e.target.value)} className="dark:bg-slate-700 dark:border-slate-600"/></div>
                        <div className="space-y-1"><Label htmlFor="interactiveFooterText" className="text-xs">Footer Text (Optional)</Label><Input id="interactiveFooterText" value={msgConf.interactive?.footer?.text || ''} onChange={(e) => handleConfigPathChange('message_config.interactive.footer.text', e.target.value)} className="dark:bg-slate-700 dark:border-slate-600"/></div>
                        <Label className="text-sm font-medium dark:text-slate-300 block pt-2">Buttons (Max 3):</Label>
                        {interactiveButtons.map((button, index) => (
                        <Card key={`ibtn-${index}`} className="p-2 space-y-1 dark:bg-slate-600/50 dark:border-slate-500">
                            <Label className="text-xs block">Button {index + 1}</Label>
                            <div className="space-y-1"><Label htmlFor={`btnTitle-${index}`} className="text-xs">Title* (max 20 chars)</Label><Input id={`btnTitle-${index}`} maxLength={20} value={button.reply?.title || ''} onChange={(e) => handleButtonChange(index, 'title', e.target.value)} className="dark:bg-slate-500"/></div>
                            <div className="space-y-1"><Label htmlFor={`btnId-${index}`} className="text-xs">ID* (max 256 chars, unique)</Label><Input id={`btnId-${index}`} maxLength={256} value={button.reply?.id || ''} onChange={(e) => handleButtonChange(index, 'id', e.target.value)} className="dark:bg-slate-500"/></div>
                            <Button type="button" variant="destructive" size="xs" onClick={() => removeInteractiveButton(index)} className="mt-1"><FiTrash2 className="mr-1 h-3 w-3"/> Remove</Button>
                        </Card>
                        ))}
                        {interactiveButtons.length < 3 && (
                        <Button type="button" variant="outline" size="sm" onClick={addInteractiveButton} className="dark:text-slate-300 dark:border-slate-600"><FiPlusCircle className="mr-1"/> Add Button</Button>
                        )}
                    </div>
                )}
                {/* TODO: Implement UI for 'interactive_list' */}
                 {msgConf.interactive?.type === 'list' && <p className="text-sm text-amber-500">UI for Interactive List is a TODO.</p>}
            </div>
        )}

        {(currentMsgType === 'template') &&
            <p className="text-sm text-amber-500 dark:text-amber-400 p-3 border-t dark:border-slate-700">
                UI for Template Message configuration is a TODO. Use Raw JSON for now.
            </p>
        }
      </div>
    );
  };

  // Specific to step_type: 'action'
  const renderActionConfig = () => {
    const actions = Array.isArray(currentConfig.actions_to_run) ? currentConfig.actions_to_run : [];
    
    const handleActionItemChange = (index, field, value) => {
        const newActions = JSON.parse(JSON.stringify(actions));
        newActions[index] = newActions[index] || {};
        newActions[index][field] = value;
        if (field === 'action_type') {
            const defaults = { action_type: value };
            if (value === 'set_context_variable') { defaults.variable_name = ''; defaults.value_template = ''; }
            // TODO: Add resets for other action_types
            newActions[index] = defaults;
        }
        handleConfigPathChange('actions_to_run', newActions);
    };
    const addActionItem = () => handleConfigPathChange('actions_to_run', [...actions, { action_type: ACTION_CONFIG_TYPES[0].value }]);
    const removeActionItem = (index) => handleConfigPathChange('actions_to_run', actions.filter((_, i) => i !== index));

    return (
      <div className="space-y-3 p-2 border dark:border-slate-700 rounded-md mt-2">
        <div className="flex justify-between items-center p-1">
            <Label className="dark:text-slate-300 font-medium">Actions to Run:</Label>
            <Button type="button" variant="outline" size="sm" onClick={addActionItem} className="dark:text-slate-300 dark:border-slate-600"><FiPlusCircle className="mr-1"/> Add Action</Button>
        </div>
        {actions.map((action, index) => (
          <Card key={index} className="p-3 space-y-2 dark:bg-slate-700/50 dark:border-slate-600">
            <div className="flex justify-between items-center">
                <Label className="text-xs font-medium">Action {index + 1}</Label>
                <Button type="button" variant="ghost" size="icon" onClick={() => removeActionItem(index)} className="h-7 w-7 text-red-500"><FiTrash2 size={14}/></Button>
            </div>
            <div className="space-y-1">
              <Label htmlFor={`actionType-${index}`} className="text-xs">Type</Label>
              <Select value={action.action_type || ''} onValueChange={(val) => handleActionItemChange(index, 'action_type', val)}>
                <SelectTrigger id={`actionType-${index}`} className="dark:bg-slate-600"><SelectValue /></SelectTrigger>
                <SelectContent className="dark:bg-slate-600 dark:text-slate-50">
                  {ACTION_CONFIG_TYPES.map(at => <SelectItem key={at.value} value={at.value} className="dark:hover:bg-slate-500">{at.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            {action.action_type === 'set_context_variable' && (
              <>
                <div className="space-y-1"><Label htmlFor={`actionVarName-${index}`} className="text-xs">Variable Name*</Label><Input id={`actionVarName-${index}`} value={action.variable_name || ''} onChange={(e) => handleActionItemChange(index, 'variable_name', e.target.value)} className="dark:bg-slate-600"/></div>
                <div className="space-y-1"><Label htmlFor={`actionVarValue-${index}`} className="text-xs">Value Template*</Label><Input id={`actionVarValue-${index}`} value={action.value_template || ''} onChange={(e) => handleActionItemChange(index, 'value_template', e.target.value)} className="dark:bg-slate-600"/></div>
              </>
            )}
            {/* TODO: Implement UI for other action_types */}
            {action.action_type && !['set_context_variable'].includes(action.action_type) && (
                <p className="text-xs text-amber-500 p-2">UI for '{action.action_type}' not fully implemented. Use raw JSON for now.</p>
             )}
          </Card>
        ))}
        {actions.length === 0 && <p className="text-xs text-center text-slate-500 dark:text-slate-400 py-2">No actions defined.</p>}
      </div>
    );
  };

  // Specific to step_type: 'question'
  const renderQuestionConfig = () => (
      <div className="space-y-3 p-2 border dark:border-slate-700 rounded-md mt-2">
          <Label className="dark:text-slate-300 font-medium">Question Prompt (Message Config):</Label>
          <Textarea value={JSON.stringify(currentConfig.message_config || {message_type: "text", text:{body:""}}, null, 2)}
              onChange={(e) => { try { handleConfigPathChange('message_config', JSON.parse(e.target.value));} catch(err){ handleConfigPathChange('message_config', e.target.value); } }}
              rows={4} className="font-mono text-xs dark:bg-slate-700 dark:border-slate-600" placeholder='e.g., {"message_type":"text", "text":{"body":"What is your email?"}}'/>
          <Separator className="dark:bg-slate-600 my-2"/>
          <Label className="dark:text-slate-300 font-medium">Reply Processing (Reply Config):</Label>
          <div className="space-y-2 p-1">
              <div className="space-y-1"><Label htmlFor="replyVarName" className="text-xs">Save Reply to Variable*</Label><Input id="replyVarName" value={currentConfig.reply_config?.save_to_variable || ''} onChange={(e) => handleConfigPathChange('reply_config.save_to_variable', e.target.value)} className="dark:bg-slate-700 dark:border-slate-600"/></div>
              <div className="space-y-1">
                  <Label htmlFor="replyExpectedType" className="text-xs">Expected Reply Type</Label>
                  <Select value={currentConfig.reply_config?.expected_type || 'text'} onValueChange={(val) => handleConfigPathChange('reply_config.expected_type', val)}>
                      <SelectTrigger id="replyExpectedType" className="dark:bg-slate-700 dark:border-slate-600"><SelectValue /></SelectTrigger>
                      <SelectContent className="dark:bg-slate-700 dark:text-slate-50">
                          <SelectItem value="text">Any Text</SelectItem><SelectItem value="email">Email</SelectItem><SelectItem value="number">Number</SelectItem><SelectItem value="interactive_id">Interactive Reply ID</SelectItem>
                      </SelectContent>
                  </Select>
              </div>
              <div className="space-y-1"><Label htmlFor="replyValidationRegex" className="text-xs">Validation Regex (Optional)</Label><Input id="replyValidationRegex" value={currentConfig.reply_config?.validation_regex || ''} onChange={(e) => handleConfigPathChange('reply_config.validation_regex', e.target.value)} className="dark:bg-slate-700 dark:border-slate-600" placeholder="e.g., ^\d{5}$"/></div>
          </div>
      </div>
  );

  const renderDefaultConfigEditor = () => (
    <div className="p-2 border dark:border-slate-700 rounded-md mt-2"><div className="p-1">
        <Label className="dark:text-slate-300">Raw Config (JSON for {step.step_type_display || step.step_type})</Label>
        <Textarea value={typeof currentConfig === 'string' ? currentConfig : JSON.stringify(currentConfig, null, 2)}
            onChange={(e) => handleRawConfigChange(e.target.value)}
            rows={10} className="font-mono text-xs dark:bg-slate-700 dark:border-slate-600" />
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">No specific UI for this step type, or it's complex. Edit JSON directly.</p>
    </div></div>
  );

  // Main render switch for step_type specific config UI
  const renderStepSpecificConfigUI = () => {
    switch (step.step_type) {
      case 'send_message': return renderSendMessageConfig();
      case 'action': return renderActionConfig();
      case 'question': return renderQuestionConfig();
      case 'start_flow_node': return <p className="text-sm text-slate-500 dark:text-slate-400 p-3">Start nodes define the entry point. No specific runtime config usually needed here.</p>;
      case 'end_flow':
        const hasEndMsgConf = currentConfig.message_config !== undefined;
        return (
            <div className="p-2 border dark:border-slate-700 rounded-md mt-2"><div className="p-1">
                <Label className="dark:text-slate-300 font-medium">Optional End Message (Uses Send Message Config Structure)</Label>
                {!hasEndMsgConf && <Button variant="link" size="sm" className="p-0 h-auto dark:text-blue-400 text-xs mt-1 block" onClick={() => handleConfigPathChange('message_config', {message_type:"text", text:{body:"Thank you!"}})}>Add end message?</Button>}
                {hasEndMsgConf && <Textarea value={JSON.stringify(currentConfig.message_config || {}, null, 2)} onChange={(e) => { try { handleConfigPathChange('message_config', JSON.parse(e.target.value));} catch(err){/* keep string */} }} rows={4} className="font-mono text-xs dark:bg-slate-700 dark:border-slate-600 mt-1"/> }
            </div></div>
        );
      default: // For 'condition', 'wait_for_reply', or other unhandled types
        return renderDefaultConfigEditor();
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open && !isSavingStep) onClose(); else if (isSavingStep) toast.info("Save in progress...") }}>
      <DialogContent className="sm:max-w-lg md:max-w-xl lg:max-w-2xl dark:bg-slate-800 dark:text-slate-50">
        <DialogHeader>
          <DialogTitle className="text-xl">Edit Step: <span className="font-semibold text-blue-600 dark:text-blue-400">{stepName || step.name}</span></DialogTitle>
          <DialogDescription>Type: <Badge variant="outline" className="dark:border-slate-600 dark:text-slate-300">{step.step_type_display || step.step_type}</Badge></DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-4 max-h-[70vh] overflow-y-auto pr-3 custom-scrollbar"> {/* Added custom-scrollbar class for potential styling */}
          <div className="space-y-1">
            <Label htmlFor="stepNameEditModal" className="dark:text-slate-300">Step Name*</Label>
            <Input id="stepNameEditModal" value={stepName} onChange={(e) => setStepName(e.target.value)} className="dark:bg-slate-700 dark:border-slate-600" />
          </div>
          {step.step_type !== 'start_flow_node' && ( // Start node typically doesn't toggle entry point status this way
            <div className="flex items-center space-x-2">
              <Switch id={`isEntryPointEditModal-${step.id}`} checked={isEntryPoint} onCheckedChange={setIsEntryPoint} className="data-[state=checked]:bg-green-500"/>
              <Label htmlFor={`isEntryPointEditModal-${step.id}`} className="dark:text-slate-300 cursor-pointer">Is Entry Point for Flow</Label>
            </div>
          )}
          <Separator className="my-3 dark:bg-slate-700" />
          <Label className="dark:text-slate-300 text-base font-medium">Step Configuration:</Label>
          {renderStepSpecificConfigUI()}
        </div>
        <DialogFooter className="mt-4 pt-4 border-t dark:border-slate-700">
          <Button variant="outline" onClick={onClose} disabled={isSavingStep} className="dark:text-slate-300 dark:border-slate-600">Cancel</Button>
          <Button onClick={handleSave} disabled={isSavingStep} className="bg-blue-600 hover:bg-blue-700 text-white min-w-[120px]">
            {isSavingStep ? <FiLoader className="animate-spin mr-2 h-4 w-4" /> : <FiSave className="mr-2 h-4 w-4" />}
            {isSavingStep ? "Saving..." : "Save Changes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}