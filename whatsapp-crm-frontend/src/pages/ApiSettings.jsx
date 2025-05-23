// Filename: src/pages/ApiSettings.jsx
import React, { useEffect, useState, useCallback } from 'react';
import { useForm, Controller } from 'react-hook-form';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { toast } from 'sonner';
import { Separator } from '@/components/ui/separator';
import { FiEye, FiEyeOff, FiHelpCircle, FiSave, FiPlus, FiLoader, FiAlertCircle, FiSettings,FiInfo } from 'react-icons/fi';
import { Tooltip, TooltipProvider, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue, SelectGroup, SelectLabel } from "@/components/ui/select";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";

// Assuming apiCall helper is in a shared service file
// For this example, let's re-include it. In your app, import it.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const getAuthToken = () => localStorage.getItem('accessToken');

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

const DEFAULT_API_VERSION = 'v19.0'; // Or your current preferred default like 'v22.0'

const defaultFormValues = {
  name: '',
  verify_token: '',
  access_token: '',
  app_secret: '', // Added for webhook security
  phone_number_id: '',
  waba_id: '',
  api_version: DEFAULT_API_VERSION,
  is_active: false,
};

export default function ApiSettings() {
  const [isLoadingPage, setIsLoadingPage] = useState(true);
  const [configs, setConfigs] = useState([]);
  const [selectedConfigId, setSelectedConfigId] = useState(''); // Store ID of config to edit
  const [showAccessToken, setShowAccessToken] = useState(false);
  const [showVerifyToken, setShowVerifyToken] = useState(false);
  const [showAppSecret, setShowAppSecret] = useState(false); // For app_secret field

  const { register, handleSubmit, reset, control, formState: { isSubmitting, errors, dirtyFields } } = useForm({
    defaultValues: defaultFormValues
  });

  const fetchConfigs = useCallback(async () => {
    setIsLoadingPage(true);
    try {
      const data = await apiCall('/crm-api/meta/api/configs/');
      const fetchedConfigs = data.results || data || [];
      setConfigs(fetchedConfigs);

      const currentSelected = fetchedConfigs.find(c => c.id === parseInt(selectedConfigId)) ||
                              fetchedConfigs.find(c => c.is_active) ||
                              fetchedConfigs[0];
      
      if (currentSelected) {
        setSelectedConfigId(currentSelected.id.toString());
        reset({ // Populate form with fetched data
          name: currentSelected.name || '',
          verify_token: currentSelected.verify_token || '',
          access_token: currentSelected.access_token || '', // API might not return this for security if already set
          app_secret: currentSelected.app_secret || '',     // Same for app_secret
          phone_number_id: currentSelected.phone_number_id || '',
          waba_id: currentSelected.waba_id || '',
          api_version: currentSelected.api_version || DEFAULT_API_VERSION,
          is_active: currentSelected.is_active || false,
        });
      } else { // No configs, prepare for new
        setSelectedConfigId('');
        reset(defaultFormValues);
      }
    } catch (error) {
      // Error already toasted by apiCall
      console.error("Error fetching configs:", error);
    } finally {
      setIsLoadingPage(false);
    }
  }, [reset, selectedConfigId]); // Added selectedConfigId

  useEffect(() => {
    fetchConfigs();
  }, [fetchConfigs]); // Ran only once on mount, or if fetchConfigs itself changes (which it doesn't)

  const handleConfigSelectionChange = (id) => {
    setSelectedConfigId(id);
    if (id === 'new') {
      reset(defaultFormValues);
    } else {
      const configToLoad = configs.find(c => c.id.toString() === id);
      if (configToLoad) {
        reset({
          name: configToLoad.name,
          verify_token: configToLoad.verify_token,
          access_token: '', // Don't pre-fill sensitive tokens on load, user must re-enter if changing
          app_secret: '',   // Same for app_secret
          phone_number_id: configToLoad.phone_number_id,
          waba_id: configToLoad.waba_id,
          api_version: configToLoad.api_version,
          is_active: configToLoad.is_active,
        });
      }
    }
  };


  const onSubmit = async (data) => {
    const isNewConfig = !selectedConfigId || selectedConfigId === 'new';
    const method = isNewConfig ? 'POST' : 'PUT';
    const url = isNewConfig
      ? `/crm-api/meta/api/configs/`
      : `/crm-api/meta/api/configs/${selectedConfigId}/`;

    const payload = { ...data, is_active: Boolean(data.is_active) };

    // For PUT, only send fields that were actually changed (dirty) or are always required
    // Or if the API and serializer handle partial updates (PATCH) well.
    // For simplicity with PUT, we send all form data.
    // If access_token or app_secret are empty and it's an update, don't send them
    // to avoid overwriting with empty values if user didn't intend to change.
    if (!isNewConfig) {
        if (!dirtyFields.access_token && !data.access_token) delete payload.access_token;
        if (!dirtyFields.app_secret && !data.app_secret) delete payload.app_secret;
        if (!dirtyFields.verify_token && !data.verify_token) delete payload.verify_token;
    }


    try {
      const result = await apiCall(url, method, payload);
      toast.success(`Configuration "${result.name}" ${isNewConfig ? 'created' : 'updated'} successfully!`);
      
      // If a config was made active, others might have been deactivated by the backend.
      // The most reliable way to update UI is to refetch all configs.
      fetchConfigs(); 
      // If it was a new config, select it.
      if (isNewConfig && result.id) {
          setSelectedConfigId(result.id.toString());
          // Form is already reset by fetchConfigs -> reset
      }

    } catch (error) {
      // Error already toasted by apiCall.
      // err.data from apiCall might contain field-specific errors.
      // You could parse err.data here and use setError from react-hook-form if needed.
      // Example: if (error.data && typeof error.data === 'object') {
      //   Object.entries(error.data).forEach(([fieldName, messages]) => {
      //     setError(fieldName, { type: 'server', message: Array.isArray(messages) ? messages.join(', ') : messages });
      //   });
      // }
    }
  };

  if (isLoadingPage) {
    // ... (keep your existing Skeleton loader) ...
    return (
      <div className="max-w-2xl mx-auto p-4 md:p-0 animate-pulse">
        <div className="h-8 bg-gray-200 dark:bg-gray-700 rounded w-1/2 mb-8"></div>
        <div className="space-y-6">
          {[...Array(7)].map((_, i) => (
            <div key={i} className="space-y-2">
              <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-1/4"></div>
              <div className="h-10 bg-gray-200 dark:bg-gray-700 rounded"></div>
            </div>
          ))}
          <div className="h-10 bg-gray-300 dark:bg-gray-600 rounded w-1/4 mt-4"></div>
        </div>
      </div>
    );
  }

  const currentEditingName = selectedConfigId && selectedConfigId !== 'new'
    ? configs.find(c => c.id.toString() === selectedConfigId)?.name
    : 'New Configuration';

  return (
    <div className="max-w-2xl mx-auto p-4 sm:p-6 md:p-8">
      <Card className="dark:bg-slate-800 dark:border-slate-700 shadow-xl">
        <CardHeader>
          <CardTitle className="text-2xl font-bold text-gray-800 dark:text-gray-100 flex items-center gap-2">
            <FiSettings className="text-blue-500" />
            Meta App API Configuration
          </CardTitle>
          <CardDescription className="dark:text-slate-400">
            Manage settings for connecting to the WhatsApp Business API.
            {selectedConfigId && selectedConfigId !== 'new' ? ` Editing: "${currentEditingName}"` : " Creating new configuration."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
            <div className="flex flex-col sm:flex-row gap-4 items-end">
                <div className="w-full sm:flex-grow space-y-1">
                    <Label htmlFor="config-select" className="text-sm font-medium dark:text-slate-300">Load Configuration</Label>
                    <Select onValueChange={handleConfigSelectionChange} value={selectedConfigId || 'new'}>
                        <SelectTrigger id="config-select" className="w-full dark:bg-slate-700 dark:border-slate-600">
                            <SelectValue placeholder="Select a configuration..." />
                        </SelectTrigger>
                        <SelectContent className="dark:bg-slate-700 dark:text-slate-50">
                            <SelectGroup>
                                <SelectLabel className="dark:text-slate-400">Existing Configs</SelectLabel>
                                {configs.length === 0 && <SelectItem value="-" disabled>No configurations saved</SelectItem>}
                                {configs.map(conf => (
                                <SelectItem key={conf.id} value={conf.id.toString()} className="dark:hover:bg-slate-600 dark:focus:bg-slate-600">
                                    {conf.name} {conf.is_active && "(Active)"}
                                </SelectItem>
                                ))}
                            </SelectGroup>
                            <Separator className="my-1 dark:bg-slate-600"/>
                            <SelectItem value="new" className="dark:hover:bg-slate-600 dark:focus:bg-slate-600">
                                <span className="flex items-center gap-2"><FiPlus /> Create New Configuration</span>
                            </SelectItem>
                        </SelectContent>
                    </Select>
                </div>
            </div>
            <Separator className="dark:bg-slate-700"/>

            <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
            <div>
              <Label htmlFor="name" className="text-sm font-medium dark:text-slate-300">Configuration Name*</Label>
              <Input id="name" {...register('name', { required: 'Name is required.' })} placeholder="e.g., Primary Business Account" className="mt-1 w-full dark:bg-slate-700 dark:border-slate-600" disabled={isSubmitting} />
              {errors.name && <p className="text-xs text-red-500 mt-1">{errors.name.message}</p>}
            </div>

            {/* Verify Token */}
            <div className="relative space-y-1">
              <Label htmlFor="verify_token" className="text-sm font-medium dark:text-slate-300">Webhook Verify Token*</Label>
              <div className="flex items-center mt-1">
                <Input id="verify_token" type={showVerifyToken ? "text" : "password"} {...register('verify_token', { required: 'Verify token is required.' })} placeholder="Your secure webhook token" className="w-full dark:bg-slate-700 dark:border-slate-600" disabled={isSubmitting} />
                <Button type="button" variant="ghost" size="icon" className="ml-2 dark:text-slate-400 dark:hover:text-slate-200" onClick={() => setShowVerifyToken(!showVerifyToken)}><span className="sr-only">Toggle Verify Token Visibility</span>{showVerifyToken ? <FiEyeOff /> : <FiEye />}</Button>
              </div>
              {errors.verify_token && <p className="text-xs text-red-500 mt-1">{errors.verify_token.message}</p>}
            </div>
            
            {/* Access Token */}
            <div className="relative space-y-1">
              <Label htmlFor="access_token" className="text-sm font-medium dark:text-slate-300">Permanent Access Token*</Label>
              <div className="flex items-center mt-1">
                <Input id="access_token" type={showAccessToken ? "text" : "password"} {...register('access_token', { required: selectedConfigId === 'new' || dirtyFields.access_token ? 'Access token is required.' : false })} placeholder="Meta Permanent Access Token" className="w-full dark:bg-slate-700 dark:border-slate-600" disabled={isSubmitting} />
                <Button type="button" variant="ghost" size="icon" className="ml-2 dark:text-slate-400 dark:hover:text-slate-200" onClick={() => setShowAccessToken(!showAccessToken)}><span className="sr-only">Toggle Access Token Visibility</span>{showAccessToken ? <FiEyeOff /> : <FiEye />}</Button>
              </div>
              {errors.access_token && <p className="text-xs text-red-500 mt-1">{errors.access_token.message}</p>}
               {!selectedConfigId || selectedConfigId === 'new' ? null : <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Leave empty if not changing.</p>}
            </div>

            {/* App Secret (NEW) */}
            <div className="relative space-y-1">
              <Label htmlFor="app_secret" className="text-sm font-medium dark:text-slate-300">App Secret* <span className="text-xs">(for webhook security)</span></Label>
              <div className="flex items-center mt-1">
                <Input id="app_secret" type={showAppSecret ? "text" : "password"} {...register('app_secret', { required: selectedConfigId === 'new' || dirtyFields.app_secret ? 'App Secret is required.' : false })} placeholder="Your Meta App Secret" className="w-full dark:bg-slate-700 dark:border-slate-600" disabled={isSubmitting} />
                <Button type="button" variant="ghost" size="icon" className="ml-2 dark:text-slate-400 dark:hover:text-slate-200" onClick={() => setShowAppSecret(!showAppSecret)}><span className="sr-only">Toggle App Secret Visibility</span>{showAppSecret ? <FiEyeOff /> : <FiEye />}</Button>
              </div>
              {errors.app_secret && <p className="text-xs text-red-500 mt-1">{errors.app_secret.message}</p>}
              {!selectedConfigId || selectedConfigId === 'new' ? null : <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Leave empty if not changing.</p>}
            </div>

            {/* Phone Number ID, WABA ID, API Version */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-4">
                <div className="space-y-1"><Label htmlFor="phone_number_id" className="dark:text-slate-300">Phone Number ID*</Label><Input id="phone_number_id" {...register('phone_number_id', { required: 'Phone Number ID required.' })} className="mt-1 w-full dark:bg-slate-700 dark:border-slate-600" disabled={isSubmitting} />{errors.phone_number_id && <p className="text-xs text-red-500 mt-1">{errors.phone_number_id.message}</p>}</div>
                <div className="space-y-1"><Label htmlFor="waba_id" className="dark:text-slate-300">WABA ID*</Label><Input id="waba_id" {...register('waba_id', { required: 'WABA ID required.' })} className="mt-1 w-full dark:bg-slate-700 dark:border-slate-600" disabled={isSubmitting} />{errors.waba_id && <p className="text-xs text-red-500 mt-1">{errors.waba_id.message}</p>}</div>
            </div>
            <div className="space-y-1">
                <Label htmlFor="api_version" className="dark:text-slate-300">API Version*</Label>
                <Input id="api_version" {...register('api_version', { required: 'API version required.' })} defaultValue={DEFAULT_API_VERSION} className="mt-1 w-full dark:bg-slate-700 dark:border-slate-600" disabled={isSubmitting} />
                {errors.api_version && <p className="text-xs text-red-500 mt-1">{errors.api_version.message}</p>}
            </div>

            <div className="flex items-center space-x-3 pt-2">
              <Controller name="is_active" control={control} render={({ field }) => (<Switch id="is_active" checked={field.value} onCheckedChange={field.onChange} disabled={isSubmitting} className="data-[state=checked]:bg-green-500"/>)} />
              <Label htmlFor="is_active" className="text-sm font-medium dark:text-slate-300 cursor-pointer">Set as Active Configuration</Label>
              <TooltipProvider><Tooltip><TooltipTrigger type="button" className="text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300"><FiHelpCircle size={16}/></TooltipTrigger><TooltipContent className="max-w-xs"><p className="text-xs">Only one configuration can be active. The active one is used for sending messages and webhook verification.</p></TooltipContent></Tooltip></TooltipProvider>
            </div>
            
            <div className="pt-2">
                <Button type="submit" className="w-full sm:w-auto bg-green-600 hover:bg-green-700 dark:bg-green-500 dark:hover:bg-green-600 text-white" disabled={isSubmitting || isLoadingPage}>
                {isSubmitting ? <FiLoader className="animate-spin mr-2"/> : <FiSave className="mr-2 h-4 w-4" />}
                {isSubmitting ? 'Saving...' : (selectedConfigId && selectedConfigId !== 'new' ? 'Update Configuration' : 'Create Configuration')}
                </Button>
            </div>
          </form>
          
          {/* Informational Box */}
          <div className="mt-8 p-4 bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-700/50 rounded-lg">
            {/* ... (your existing important notes section) ... */}
            <div className="flex items-start"><FiInfo className="h-5 w-5 text-blue-600 dark:text-blue-400 mr-3 mt-0.5 flex-shrink-0"/><div><h3 className="text-sm font-semibold text-blue-700 dark:text-blue-300">Important:</h3><ul className="list-disc list-inside text-xs text-blue-600 dark:text-blue-400/80 mt-1 space-y-1"><li>Ensure <code className="bg-blue-100 dark:bg-blue-800/50 px-1 py-0.5 rounded text-xs">Verify Token</code> matches Meta App Dashboard.</li><li>Keep <code className="bg-blue-100 dark:bg-blue-800/50 px-1 py-0.5 rounded text-xs">Access Token</code> & <code className="bg-blue-100 dark:bg-blue-800/50 px-1 py-0.5 rounded text-xs">App Secret</code> secure.</li><li>IDs can be found in Meta Business Manager.</li></ul></div></div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}