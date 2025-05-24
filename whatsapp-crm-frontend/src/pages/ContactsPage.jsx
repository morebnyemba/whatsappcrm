// src/pages/ContactsPage.jsx
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose, DialogTrigger
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue, SelectGroup, SelectLabel
} from '@/components/ui/select';
import { toast } from 'sonner';
import { useForm, Controller } from 'react-hook-form';
import {
  FiUser, FiUsers, FiMessageSquare, FiSearch, FiLoader, FiAlertCircle, FiEdit, FiSave, FiMail,
  FiPhone, FiTag, FiBriefcase, FiMapPin, FiInfo, FiCalendar, FiBarChart2, FiSmartphone, FiGlobe
} from 'react-icons/fi';
import { formatDistanceToNow, parseISO, format, isValid as isValidDate } from 'date-fns';

// --- API Configuration & Helper ---
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const getAuthToken = () => localStorage.getItem('accessToken');

async function apiCall(endpoint, method = 'GET', body = null, isPaginatedFallback = false) {
    const token = getAuthToken();
    const headers = {
        ...(!body || !(body instanceof FormData) && { 'Content-Type': 'application/json' }),
        ...(token && { 'Authorization': `Bearer ${token}` }),
    };
    if (body && !(body instanceof FormData) && method !== 'GET') headers['Content-Type'] = 'application/json';
    
    const config = { method, headers, ...(body && method !== 'GET' && { body: (body instanceof FormData ? body : JSON.stringify(body)) }) };
    try {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, config);
        if (!response.ok) {
            let errorData = { detail: `Request to ${endpoint} failed: ${response.status} ${response.statusText}` };
            try {
                const contentType = response.headers.get("content-type");
                if (contentType && contentType.indexOf("application/json") !== -1) { errorData = await response.json(); }
                else { errorData.detail = (await response.text()) || errorData.detail; }
            } catch (e) { console.error("Failed to parse error response for a failed request:", e); }
            const errorMessage = errorData.detail || 
                               (typeof errorData === 'object' && errorData !== null && !errorData.detail ? 
                                 Object.entries(errorData).map(([k,v])=>`${k.replace(/_/g, " ")}: ${Array.isArray(v) ? v.join(', ') : String(v)}`).join('; ') : 
                                 `API Error ${response.status}`);
            const err = new Error(errorMessage); err.data = errorData; err.isApiError = true; throw err;
        }
        if (response.status === 204 || (response.headers.get("content-length") || "0") === "0") {
            return isPaginatedFallback ? { results: [], count: 0, next: null, previous: null } : null;
        }
        const data = await response.json();
        return isPaginatedFallback ? { 
            results: data.results || (Array.isArray(data) ? data : []), 
            count: data.count === undefined ? (Array.isArray(data) ? data.length : 0) : data.count,
            next: data.next, previous: data.previous 
        } : data;
    } catch (error) {
        console.error(`API call to ${method} ${API_BASE_URL}${endpoint} failed:`, error);
        if (!error.isApiError || !error.message.includes("(toasted)")) {
            toast.error(error.message || 'API error'); error.message = (error.message || "") + " (toasted)";
        } throw error;
    }
}

const ProfileFieldDisplay = ({ label, value, icon, children, isDate = false, isTagList = false }) => {
    let displayValue = value;
    if (isDate && value) {
        try {
            const dateObj = parseISO(value);
            if (isValidDate(dateObj)) displayValue = format(dateObj, 'PPP'); // e.g., May 24th, 2025
            else displayValue = value; // Show original if not a valid date string
        } catch (e) { displayValue = value; } // In case parseISO throws for completely invalid string
    }
    if (!value && !children && value !== false && value !== 0) return null;
    return (
        <div className="py-2.5 sm:grid sm:grid-cols-3 sm:gap-4 border-b dark:border-slate-700 last:border-b-0">
            <dt className="text-sm font-medium text-slate-500 dark:text-slate-400 flex items-center">
                {icon && React.cloneElement(icon, { className: "mr-2 h-4 w-4 opacity-80"})}
                {label}
            </dt>
            <dd className="mt-1 text-sm text-slate-900 dark:text-slate-50 sm:mt-0 sm:col-span-2">
                {children ? children : 
                 isTagList && Array.isArray(displayValue) ? 
                    (displayValue.length > 0 ? displayValue.map(tag => <Badge key={tag} variant="secondary" className="mr-1 mb-1 dark:bg-slate-600 dark:text-slate-200">{tag}</Badge>) : <span className="italic text-slate-400 dark:text-slate-500">No tags</span>) :
                 (displayValue === null || displayValue === '' ? <span className="italic text-slate-400 dark:text-slate-500">Not set</span> : String(displayValue))
                }
            </dd>
        </div>
    );
};

const GENDER_CHOICES = [ { value: 'male', label: 'Male' }, { value: 'female', label: 'Female' }, { value: 'other', label: 'Other' }, { value: 'prefer_not_to_say', label: 'Prefer not to say' }];
const LIFECYCLE_STAGE_CHOICES = [ { value: 'lead', label: 'Lead' }, { value: 'opportunity', label: 'Opportunity' }, { value: 'customer', label: 'Customer' }, { value: 'vip', label: 'VIP Customer' }, { value: 'churned', label: 'Churned' }, { value: 'other', label: 'Other' }];

export default function ContactsPage() {
  const [contacts, setContacts] = useState([]);
  const [selectedContactDetails, setSelectedContactDetails] = useState(null);
  const [isLoadingContacts, setIsLoadingContacts] = useState(true);
  const [isLoadingDetails, setIsLoadingDetails] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [isEditProfileModalOpen, setIsEditProfileModalOpen] = useState(false);
  const [pagination, setPagination] = useState({ count: 0, next: null, previous: null, currentPage: 1 });
  
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const { register, handleSubmit, reset, control, formState: { isSubmitting, errors: formErrors }, setValue } = useForm({
      defaultValues: { // Initialize with all possible fields to avoid uncontrolled to controlled input warnings
          contact_name: '', is_blocked: false, needs_human_intervention: false,
          first_name: '', last_name: '', email: '', ecocash_number: '', secondary_phone_number: '',
          date_of_birth: '', gender: '', company_name: '', job_title: '',
          address_line_1: '', address_line_2: '', city: '', state_province: '', postal_code: '', country: '',
          lifecycle_stage: 'lead', acquisition_source: '', tags: '', notes: '',
          preferences: '{}', custom_attributes: '{}'
      }
  });

  const fetchContacts = useCallback(async (page = 1, currentSearchTerm = '') => {
    setIsLoadingContacts(true);
    try {
      const filterParam = searchParams.get('filter');
      const queryParams = new URLSearchParams({ page: page.toString() });
      if (currentSearchTerm) queryParams.append('search', currentSearchTerm);
      if (filterParam === 'needs_intervention') queryParams.append('needs_human_intervention', 'true');
      
      const endpoint = `/crm-api/conversations/contacts/?${queryParams.toString()}`;
      const data = await apiCall(endpoint, 'GET', null, true);
      setContacts(data.results || []);
      setPagination({ count: data.count || 0, next: data.next, previous: data.previous, currentPage: page });
    } catch (error) { /* toast handled by apiCall */ } 
    finally { setIsLoadingContacts(false); }
  }, [searchParams]);

  useEffect(() => {
    fetchContacts(1, searchTerm);
  }, [fetchContacts, searchTerm]); // Re-fetch if searchTerm changes

  const handleSelectContact = useCallback(async (contact) => {
    setIsLoadingDetails(true);
    setSelectedContactDetails(null); 
    try {
      const detailedData = await apiCall(`/crm-api/conversations/contacts/${contact.id}/`);
      setSelectedContactDetails(detailedData);
      reset({ // Pre-fill form for editing
        contact_name: detailedData.name || '',
        is_blocked: detailedData.is_blocked || false,
        needs_human_intervention: detailedData.needs_human_intervention || false,
        first_name: detailedData.customer_profile?.first_name || '',
        last_name: detailedData.customer_profile?.last_name || '',
        email: detailedData.customer_profile?.email || '',
        ecocash_number: detailedData.customer_profile?.ecocash_number || '',
        secondary_phone_number: detailedData.customer_profile?.secondary_phone_number || '',
        date_of_birth: detailedData.customer_profile?.date_of_birth || '', // HTML date input expects YYYY-MM-DD
        gender: detailedData.customer_profile?.gender || '',
        company_name: detailedData.customer_profile?.company_name || '',
        job_title: detailedData.customer_profile?.job_title || '',
        address_line_1: detailedData.customer_profile?.address_line_1 || '',
        address_line_2: detailedData.customer_profile?.address_line_2 || '',
        city: detailedData.customer_profile?.city || '',
        state_province: detailedData.customer_profile?.state_province || '',
        postal_code: detailedData.customer_profile?.postal_code || '',
        country: detailedData.customer_profile?.country || '',
        lifecycle_stage: detailedData.customer_profile?.lifecycle_stage || 'lead',
        acquisition_source: detailedData.customer_profile?.acquisition_source || '',
        tags: (detailedData.customer_profile?.tags || []).join(', '),
        notes: detailedData.customer_profile?.notes || '',
        preferences: JSON.stringify(detailedData.customer_profile?.preferences || {}, null, 2),
        custom_attributes: JSON.stringify(detailedData.customer_profile?.custom_attributes || {}, null, 2),
      });
    } catch (error) { /* toast handled by apiCall */ } 
    finally { setIsLoadingDetails(false); }
  }, [reset]);

  const onProfileFormSubmit = async (formData) => {
    if (!selectedContactDetails?.id) return;
    const contactId = selectedContactDetails.id;

    const contactPayload = {
        name: formData.contact_name,
        is_blocked: formData.is_blocked,
        needs_human_intervention: formData.needs_human_intervention,
    };
    
    let parsedPreferences, parsedCustomAttributes;
    try { parsedPreferences = JSON.parse(formData.preferences || '{}'); } catch (e) { toast.error("Invalid JSON for Preferences."); return; }
    try { parsedCustomAttributes = JSON.parse(formData.custom_attributes || '{}'); } catch (e) { toast.error("Invalid JSON for Custom Attributes."); return; }

    const profilePayload = {
        first_name: formData.first_name, last_name: formData.last_name, email: formData.email,
        secondary_phone_number: formData.secondary_phone_number, ecocash_number: formData.ecocash_number,
        date_of_birth: formData.date_of_birth || null, gender: formData.gender || null,
        company_name: formData.company_name, job_title: formData.job_title,
        address_line_1: formData.address_line_1, address_line_2: formData.address_line_2, city: formData.city,
        state_province: formData.state_province, postal_code: formData.postal_code, country: formData.country,
        lifecycle_stage: formData.lifecycle_stage, acquisition_source: formData.acquisition_source,
        tags: formData.tags.split(',').map(tag => tag.trim()).filter(tag => tag),
        notes: formData.notes, preferences: parsedPreferences, custom_attributes: parsedCustomAttributes,
    };

    try {
      // Using Promise.allSettled to ensure both calls are attempted
      const [contactUpdateResult, profileUpdateResult] = await Promise.allSettled([
        apiCall(`/crm-api/conversations/contacts/${contactId}/`, 'PATCH', contactPayload),
        apiCall(`/crm-api/customer-data/profiles/${contactId}/`, 'PATCH', profilePayload) // contactId is PK of CustomerProfile
      ]);

      let anyError = false;
      if (contactUpdateResult.status === 'rejected') {
          toast.error(`Failed to update contact: ${contactUpdateResult.reason.message}`);
          anyError = true;
      }
      if (profileUpdateResult.status === 'rejected') {
          toast.error(`Failed to update profile: ${profileUpdateResult.reason.message}`);
          anyError = true;
      }

      if (!anyError) {
        toast.success("Customer data updated successfully!");
        setIsEditProfileModalOpen(false);
        // Re-fetch the selected contact's details to show updated info
        handleSelectContact({ id: contactId, name: formData.contact_name }); // Pass basic info to re-trigger full fetch
        // Also update the main contacts list with the potentially changed name or status
        setContacts(prevList => prevList.map(c => c.id === contactId ? {...c, name: formData.contact_name, is_blocked: formData.is_blocked, needs_human_intervention: formData.needs_human_intervention } : c));

      }
    } catch (error) { /* Should be caught by individual apiCalls */ }
  };

  const handlePageChange = (newPage) => {
    if (newPage >= 1 && newPage <= Math.ceil(pagination.count / 20)) { // Assuming page size 20
        fetchContacts(newPage, searchTerm);
    }
  };


  return (
    <div className="flex h-[calc(100vh-var(--header-height,4rem)-1rem)] border dark:border-slate-700 rounded-lg shadow-md overflow-hidden">
      {/* Contacts List Panel */}
      <div className="w-full sm:w-2/5 md:w-1/3 min-w-[300px] max-w-[450px] border-r dark:border-slate-700 flex flex-col bg-slate-50 dark:bg-slate-800/50">
        <div className="p-3 border-b dark:border-slate-700">
          <div className="relative">
            <FiSearch className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <Input type="search" placeholder="Search contacts..." className="pl-9 dark:bg-slate-700 dark:border-slate-600" value={searchTerm} onChange={(e)=>setSearchTerm(e.target.value)}/>
          </div>
        </div>
        <ScrollArea className="flex-1">
          {isLoadingContacts && contacts.length === 0 && (<div className="p-4 text-center"><FiLoader className="animate-spin h-6 w-6 mx-auto my-3 text-slate-500" /> <p className="text-xs text-slate-400">Loading contacts...</p></div>)}
          {!isLoadingContacts && contacts.length === 0 && (<div className="p-4 text-center text-sm text-slate-500 dark:text-slate-400">No contacts match your search or filter.</div>)}
          {contacts.map(contact => (
            <div key={contact.id} onClick={() => handleSelectContact(contact)}
              className={`p-3 border-b dark:border-slate-700 cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors ${selectedContactDetails?.id === contact.id ? 'bg-blue-100 dark:bg-blue-900/50 border-l-4 border-blue-500 dark:border-blue-400' : 'border-l-4 border-transparent'}`}>
              <div className="flex items-center space-x-3">
                <Avatar className="h-9 w-9"><AvatarImage src={`https://ui-avatars.com/api/?name=${encodeURIComponent(contact.name || contact.whatsapp_id)}&background=random&size=96`} /><AvatarFallback>{(contact.name || contact.whatsapp_id || 'U').substring(0,1).toUpperCase()}</AvatarFallback></Avatar>
                <div className="flex-1 min-w-0">
                  <p className="font-medium truncate dark:text-slate-100 text-sm">{contact.name || contact.whatsapp_id}</p>
                  <p className="text-xs text-slate-500 dark:text-slate-400 truncate">
                    {contact.whatsapp_id}
                    {contact.last_seen && ` · Seen ${formatDistanceToNow(parseISO(contact.last_seen), { addSuffix: true })}`}
                  </p>
                </div>
                {contact.needs_human_intervention && <FiAlertCircle title="Needs Human Intervention" className="h-5 w-5 text-red-500 flex-shrink-0"/>}
              </div>
            </div>
          ))}
        </ScrollArea>
        {/* Pagination for Contacts List */}
        {pagination.count > 0 && (
            <div className="p-2 border-t dark:border-slate-700 flex justify-between items-center text-xs">
                <Button variant="outline" size="sm" onClick={() => handlePageChange(pagination.currentPage - 1)} disabled={!pagination.previous || isLoadingContacts}>Prev</Button>
                <span>Page {pagination.currentPage} of {Math.ceil(pagination.count / 20)}</span>
                <Button variant="outline" size="sm" onClick={() => handlePageChange(pagination.currentPage + 1)} disabled={!pagination.next || isLoadingContacts}>Next</Button>
            </div>
        )}
      </div>

      {/* Contact Details & Profile Panel */}
      <ScrollArea className="flex-1 bg-white dark:bg-slate-900">
        {isLoadingDetails && <div className="flex items-center justify-center h-full p-10"><FiLoader className="animate-spin h-10 w-10 text-blue-500"/></div>}
        {!isLoadingDetails && selectedContactDetails ? (
          <div className="p-4 sm:p-6 space-y-6">
            <Card className="dark:bg-slate-800 dark:border-slate-700">
              <CardHeader className="flex flex-col sm:flex-row justify-between sm:items-start gap-2 pb-4">
                <div className="flex items-center gap-4">
                    <Avatar className="h-16 w-16 border-2 dark:border-slate-600"><AvatarImage src={`https://ui-avatars.com/api/?name=${encodeURIComponent(selectedContactDetails.name || selectedContactDetails.whatsapp_id)}&background=random&size=128`} /><AvatarFallback className="text-2xl">{(selectedContactDetails.name || selectedContactDetails.whatsapp_id || 'U').substring(0,2).toUpperCase()}</AvatarFallback></Avatar>
                    <div>
                        <CardTitle className="text-xl md:text-2xl dark:text-slate-50">{selectedContactDetails.name || selectedContactDetails.whatsapp_id}</CardTitle>
                        <CardDescription className="dark:text-slate-400 mt-1">{selectedContactDetails.whatsapp_id}</CardDescription>
                        <div className="mt-2 flex flex-wrap gap-2">
                           {selectedContactDetails.is_blocked && <Badge variant="destructive">Blocked</Badge>}
                           {selectedContactDetails.needs_human_intervention && <Badge variant="warning">Needs Intervention</Badge>}
                        </div>
                    </div>
                </div>
                <div className="flex flex-col sm:flex-row gap-2 sm:items-center pt-2 sm:pt-0 w-full sm:w-auto">
                    <Button variant="outline" size="sm" onClick={() => navigate(`/conversation?contactId=${selectedContactDetails.id}`)} className="dark:text-slate-300 dark:border-slate-600 w-full sm:w-auto"> <FiMessageSquare className="mr-2 h-4 w-4"/> View Chat</Button>
                    <Dialog open={isEditProfileModalOpen} onOpenChange={setIsEditProfileModalOpen}>
                        <DialogTrigger asChild>
                            <Button size="sm" className="bg-blue-600 hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600 text-white w-full sm:w-auto"><FiEdit className="mr-2 h-4 w-4"/> Edit Profile</Button>
                        </DialogTrigger>
                        <DialogContent className="sm:max-w-2xl lg:max-w-3xl dark:bg-slate-800 dark:text-slate-50">
                            <DialogHeader><DialogTitle>Edit Profile: {selectedContactDetails.name || selectedContactDetails.whatsapp_id}</DialogTitle><DialogDescription>Update contact and customer profile details.</DialogDescription></DialogHeader>
                            <form onSubmit={handleSubmit(onProfileFormSubmit)} className="space-y-4 max-h-[70vh] overflow-y-auto p-1 custom-scrollbar mt-2 pr-3">
                                <h3 className="text-md font-semibold border-b pb-1 dark:text-slate-200 dark:border-slate-700">Contact Info</h3>
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                    <div><Label htmlFor="contact_name">Display Name</Label><Input id="contact_name" {...register("contact_name")} className="dark:bg-slate-700 dark:border-slate-600"/></div>
                                </div>
                                <div className="flex items-center space-x-2"><Controller name="is_blocked" control={control} render={({ field }) => <Switch id="is_blocked" checked={field.value} onCheckedChange={field.onChange} />} /><Label htmlFor="is_blocked" className="cursor-pointer">Is Blocked</Label></div>
                                <div className="flex items-center space-x-2"><Controller name="needs_human_intervention" control={control} render={({ field }) => <Switch id="needs_human_intervention" checked={field.value} onCheckedChange={field.onChange} />} /><Label htmlFor="needs_human_intervention" className="cursor-pointer">Needs Human Intervention</Label></div>
                                <Separator className="my-4 dark:bg-slate-700"/>
                                <h3 className="text-md font-semibold border-b pb-1 dark:text-slate-200 dark:border-slate-700">Profile Details</h3>
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                    <div><Label htmlFor="first_name">First Name</Label><Input id="first_name" {...register("first_name")} className="dark:bg-slate-700"/></div>
                                    <div><Label htmlFor="last_name">Last Name</Label><Input id="last_name" {...register("last_name")} className="dark:bg-slate-700"/></div>
                                    <div><Label htmlFor="email">Email</Label><Input id="email" type="email" {...register("email")} className="dark:bg-slate-700"/></div>
                                    <div><Label htmlFor="ecocash_number">Ecocash Number</Label><Input id="ecocash_number" {...register("ecocash_number")} className="dark:bg-slate-700"/></div>
                                    <div><Label htmlFor="secondary_phone_number">Secondary Phone</Label><Input id="secondary_phone_number" {...register("secondary_phone_number")} className="dark:bg-slate-700"/></div>
                                    <div><Label htmlFor="date_of_birth">Date of Birth</Label><Input id="date_of_birth" type="date" {...register("date_of_birth")} className="dark:bg-slate-700 dark:[color-scheme:dark]"/></div>
                                    <div><Label htmlFor="gender">Gender</Label><Controller name="gender" control={control} render={({ field }) => (<Select onValueChange={field.onChange} value={field.value || ""}><SelectTrigger className="dark:bg-slate-700"><SelectValue placeholder="Select gender" /></SelectTrigger><SelectContent className="dark:bg-slate-700">{GENDER_CHOICES.map(g=><SelectItem key={g.value} value={g.value}>{g.label}</SelectItem>)}</SelectContent></Select>)}/></div>
                                    <div><Label htmlFor="company_name">Company Name</Label><Input id="company_name" {...register("company_name")} className="dark:bg-slate-700"/></div>
                                    <div><Label htmlFor="job_title">Job Title</Label><Input id="job_title" {...register("job_title")} className="dark:bg-slate-700"/></div>
                                    <div><Label htmlFor="address_line_1">Address Line 1</Label><Input id="address_line_1" {...register("address_line_1")} className="dark:bg-slate-700"/></div>
                                    <div><Label htmlFor="address_line_2">Address Line 2</Label><Input id="address_line_2" {...register("address_line_2")} className="dark:bg-slate-700"/></div>
                                    <div><Label htmlFor="city">City</Label><Input id="city" {...register("city")} className="dark:bg-slate-700"/></div>
                                    <div><Label htmlFor="state_province">State/Province</Label><Input id="state_province" {...register("state_province")} className="dark:bg-slate-700"/></div>
                                    <div><Label htmlFor="postal_code">Postal Code</Label><Input id="postal_code" {...register("postal_code")} className="dark:bg-slate-700"/></div>
                                    <div><Label htmlFor="country">Country</Label><Input id="country" {...register("country")} className="dark:bg-slate-700"/></div>
                                    <div><Label htmlFor="lifecycle_stage">Lifecycle Stage</Label><Controller name="lifecycle_stage" control={control} render={({ field }) => (<Select onValueChange={field.onChange} value={field.value || ""}><SelectTrigger className="dark:bg-slate-700"><SelectValue placeholder="Select stage" /></SelectTrigger><SelectContent className="dark:bg-slate-700">{LIFECYCLE_STAGE_CHOICES.map(s=><SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}</SelectContent></Select>)}/></div>
                                    <div><Label htmlFor="acquisition_source">Acquisition Source</Label><Input id="acquisition_source" {...register("acquisition_source")} className="dark:bg-slate-700"/></div>
                                </div>
                                <div><Label htmlFor="tags">Tags (comma-separated)</Label><Input id="tags" {...register("tags")} className="dark:bg-slate-700"/></div>
                                <div><Label htmlFor="notes">Notes</Label><Textarea id="notes" {...register("notes")} className="dark:bg-slate-700" rows={3}/></div>
                                <Separator className="my-4 dark:bg-slate-700"/>
                                <h3 className="text-md font-semibold dark:text-slate-200">Advanced Data (JSON)</h3>
                                <div><Label htmlFor="preferences">Preferences (JSON)</Label><Textarea id="preferences" {...register("preferences")} className="dark:bg-slate-700 font-mono text-xs" rows={3} placeholder='e.g., {"language": "en"}'/></div>
                                <div><Label htmlFor="custom_attributes">Custom Attributes (JSON)</Label><Textarea id="custom_attributes" {...register("custom_attributes")} className="dark:bg-slate-700 font-mono text-xs" rows={3} placeholder='e.g., {"loyalty_id": "XYZ"}'/></div>

                                <DialogFooter className="pt-4">
                                    <DialogClose asChild><Button type="button" variant="outline" className="dark:text-slate-300 dark:border-slate-600">Cancel</Button></DialogClose>
                                    <Button type="submit" disabled={isSubmitting} className="bg-blue-600 hover:bg-blue-700 text-white">{isSubmitting ? <FiLoader className="animate-spin"/> : "Save Changes"}</Button>
                                </DialogFooter>
                            </form>
                        </DialogContent>
                    </Dialog>
                </div>
              </CardHeader>
              <CardContent className="pt-4">
                <dl className="divide-y dark:divide-slate-700">
                    <ProfileFieldDisplay label="Profile Name" value={selectedContactDetails.customer_profile?.first_name || selectedContactDetails.customer_profile?.last_name ? `${selectedContactDetails.customer_profile?.first_name || ''} ${selectedContactDetails.customer_profile?.last_name || ''}`.trim() : (selectedContactDetails.name || 'N/A')} icon={<FiUser/>}/>
                    <ProfileFieldDisplay label="Email" value={selectedContactDetails.customer_profile?.email} icon={<FiMail/>}/>
                    <ProfileFieldDisplay label="Ecocash No." value={selectedContactDetails.customer_profile?.ecocash_number} icon={<FiSmartphone/>}/>
                    <ProfileFieldDisplay label="Other Phone" value={selectedContactDetails.customer_profile?.secondary_phone_number} icon={<FiPhone/>}/>
                    <ProfileFieldDisplay label="Company" value={selectedContactDetails.customer_profile?.company_name} icon={<FiBriefcase/>}/>
                    <ProfileFieldDisplay label="Job Title" value={selectedContactDetails.customer_profile?.job_title} />
                    <ProfileFieldDisplay label="Date of Birth" value={selectedContactDetails.customer_profile?.date_of_birth} isDate icon={<FiCalendar/>}/>
                    <ProfileFieldDisplay label="Gender" value={LIFECYCLE_STAGE_CHOICES.find(g=>g.value === selectedContactDetails.customer_profile?.gender)?.label || selectedContactDetails.customer_profile?.gender} />
                    <ProfileFieldDisplay label="Address" icon={<FiMapPin/>}>
                        {/* ... address rendering (same as before) ... */}
                    </ProfileFieldDisplay>
                    <ProfileFieldDisplay label="Lifecycle Stage" value={LIFECYCLE_STAGE_CHOICES.find(s=>s.value === selectedContactDetails.customer_profile?.lifecycle_stage)?.label || selectedContactDetails.customer_profile?.lifecycle_stage} icon={<FiBarChart2/>}/>
                    <ProfileFieldDisplay label="Acquisition Source" value={selectedContactDetails.customer_profile?.acquisition_source} />
                    <ProfileFieldDisplay label="Tags" isTagList value={selectedContactDetails.customer_profile?.tags} icon={<FiTag/>}/>
                    <ProfileFieldDisplay label="Notes" value={selectedContactDetails.customer_profile?.notes} icon={<FiInfo/>}/>
                    <ProfileFieldDisplay label="Contact Created" value={selectedContactDetails.first_seen} isDate icon={<FiCalendar/>}/>
                    <ProfileFieldDisplay label="Last Interaction" value={selectedContactDetails.last_seen} isDate icon={<FiCalendar/>}/>
                </dl>
              </CardContent>
            </Card>
          </div>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-slate-500 dark:text-slate-400 p-10 text-center">
            <FiUsers className="h-24 w-24 mb-6 text-slate-300 dark:text-slate-600" />
            <p className="text-lg font-medium">Select a contact to view their details.</p>
            <p className="text-sm">Or use the search to find a specific contact.</p>
          </div>
        )}
      </ScrollArea>
    </div>
  );
}