// src/pages/MediaLibraryPage.jsx 
// (Rename this file to MediaPage.jsx if that's your new standard, or keep as MediaLibraryPage.jsx)
import React, { useState, useEffect, useCallback, useRef } from 'react';
import apiClient from '../services/api'; // Your centralized Axios instance
import { useAuth } from '../context/AuthContext'; 
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogClose,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Card, CardContent, CardHeader, CardTitle, CardDescription ,CardFooter} from '@/components/ui/card';
import { toast } from 'sonner';
import { FiUploadCloud, FiImage, FiVideo, FiFileText, FiMusic, FiTrash2, FiLoader, FiRefreshCw } from 'react-icons/fi';
import { motion } from 'framer-motion'; // <--- IMPORT motion
import { formatDistanceToNow, parseISO } from 'date-fns';
import { formatBytes, formatDate } from '@/lib/utils'; // Ensure these utils are correctly defined


// Asset type choices matching your backend model MediaAsset.ASSET_TYPES
const ASSET_TYPE_CHOICES = [
  { value: 'IMAGE', label: 'Image' },
  { value: 'VIDEO', label: 'Video' },
  { value: 'AUDIO', label: 'Audio' },
  { value: 'DOCUMENT', label: 'Document' },
];

const MediaAssetStatusBadge = ({ status }) => {
  const statusDisplay = status ? status.toLowerCase().replace(/_/g, " ") : 'unknown';
  const statusColors = {
    local: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300',
    pending: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
    uploading: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200', // Used if you set this status during upload
    synced: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
    error_upload: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
    error_resync: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
    expired: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
    deleted: 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400 line-through',
  };

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium capitalize ${statusColors[status] || statusColors.local}`}>
      {statusDisplay}
    </span>
  );
};

const MediaTypeIcon = ({ assetType }) => {
  const icons = {
    IMAGE: <FiImage className="h-5 w-5 text-blue-500" />,
    VIDEO: <FiVideo className="h-5 w-5 text-purple-500" />,
    AUDIO: <FiMusic className="h-5 w-5 text-green-500" />,
    DOCUMENT: <FiFileText className="h-5 w-5 text-gray-500" />,
  };
  return icons[assetType] || icons.DOCUMENT;
};

const MediaAssetRowDisplay = ({ asset, onSync, onDelete }) => {
  return (
    <TableRow>
      <TableCell className="w-12"><MediaTypeIcon assetType={asset.asset_type} /></TableCell>
      <TableCell className="font-medium break-all">
        {asset.file_display_url ? (
            <a href={asset.file_display_url} target="_blank" rel="noopener noreferrer" className="hover:underline">
                {asset.name}
            </a>
        ) : (
            asset.name
        )}
        {asset.notes && <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 truncate" title={asset.notes}>{asset.notes}</p>}
      </TableCell>
      <TableCell>{asset.asset_type_display || asset.asset_type}</TableCell>
      <TableCell>{formatBytes(asset.file_size || 0)}</TableCell>
      <TableCell><MediaAssetStatusBadge status={asset.status} /></TableCell>
      <TableCell>{asset.uploaded_at ? formatDate(asset.uploaded_at) : (asset.created_at ? formatDate(asset.created_at) : 'N/A')}</TableCell>
      <TableCell className="text-right">
        <div className="flex items-center justify-end space-x-1">
            {(asset.status !== 'SYNCED' && asset.status !== 'uploading' && asset.whatsapp_media_id === null) && (
                <Button variant="ghost" size="icon" onClick={() => onSync(asset.id)} title="Sync with Meta">
                    <FiRefreshCw className="h-4 w-4 text-blue-500" />
                </Button>
            )}
            <Button variant="ghost" size="icon" onClick={() => onDelete(asset.id)} title="Delete Asset">
            <FiTrash2 className="h-4 w-4 text-red-500" />
            </Button>
        </div>
      </TableCell>
    </TableRow>
  );
};

export default function MediaPage() {
  const [assets, setAssets] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  
  const [selectedFile, setSelectedFile] = useState(null);
  const [assetName, setAssetName] = useState(''); // Correct state for the file name
  const [assetType, setAssetType] = useState(ASSET_TYPE_CHOICES[0]?.value || 'IMAGE');
  const [assetNotes, setAssetNotes] = useState(''); // For description/notes
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef(null);

  const [filterType, setFilterType] = useState('all');
  const [filterStatus, setFilterStatus] = useState('all');
  const [refreshKey, setRefreshKey] = useState(0);

  const auth = useAuth();
  const navigate = useNavigate();

  const fetchMediaAssets = useCallback(async () => {
    if (!auth?.isAuthenticated) {
      console.log("MediaPage: Not authenticated, skipping fetch.");
      // Redirect handled by useEffect below or ProtectedRoute
      return;
    }

    setIsLoading(true);
    try {
      const params = {};
      if (filterType !== 'all') params.asset_type = filterType;
      if (filterStatus !== 'all') params.status = filterStatus;

      // Use correct endpoint
      const response = await apiClient.get('/crm-api/media/media-assets/', { params });
      setAssets(response.data?.results || response.data || []);
    } catch (error) {
      toast.error('Failed to fetch media assets.');
      console.error('Error fetching media assets:', error.response?.data || error);
      setAssets([]);
    } finally {
      setIsLoading(false);
    }
  }, [auth?.isAuthenticated, filterType, filterStatus, refreshKey]);

  useEffect(() => {
    if (auth && !auth.isLoadingAuth) { // Wait for auth to be determined
        if (auth.isAuthenticated) {
            fetchMediaAssets();
        } else {
            navigate('/login', { state: { from: location } }); // Use location from useLocation()
        }
    }
  }, [auth, fetchMediaAssets, navigate, location]); // Added location


  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file) {
      setSelectedFile(file);
      setAssetName(file.name.split('.').slice(0, -1).join('.') || file.name);
      if (file.type.startsWith('image/')) setAssetType('IMAGE');
      else if (file.type.startsWith('video/')) setAssetType('VIDEO');
      else if (file.type.startsWith('audio/')) setAssetType('AUDIO');
      else if (file.type === 'application/pdf' || 
               file.type.startsWith('application/msword') || 
               file.type.startsWith('application/vnd.openxmlformats-officedocument')) {
        setAssetType('DOCUMENT');
      } else {
        setAssetType(ASSET_TYPE_CHOICES[3]?.value || 'DOCUMENT'); // Default to Document if unknown
      }
    }
  };

  const resetUploadForm = () => {
    setSelectedFile(null);
    setAssetName('');
    setAssetNotes('');
    setAssetType(ASSET_TYPE_CHOICES[0]?.value || 'IMAGE');
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
    setIsUploadModalOpen(false); // Also close the modal
  };

  const handleUpload = async (event) => {
    event.preventDefault();
    if (!selectedFile) {
      toast.error('Please select a file to upload.');
      return;
    }
    if (!assetName.trim()) {
      toast.error('Please provide a name for the asset.');
      return;
    }
    if (!assetType) {
        toast.error('Please select an asset type.');
        return;
    }

    setIsUploading(true);
    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('name', assetName.trim());
    formData.append('asset_type', assetType); // Corrected key for backend
    if (assetNotes.trim()) {
      formData.append('notes', assetNotes.trim()); // Use 'notes' if that's your model field for description
    }

    try {
      // Use correct endpoint and apiClient adds auth headers
      const response = await apiClient.post('/crm-api/media/media-assets/', formData);
      // Axios with FormData doesn't usually need Content-Type header set manually, it does it.
      
      toast.success(response.data?.message || `Asset "${assetName}" uploaded successfully! It will be processed.`);
      resetUploadForm();
      setRefreshKey(prev => prev + 1);
    } catch (error) {
      const errorDetail = error.response?.data;
      let errorMsg = "Failed to upload asset.";
      if (typeof errorDetail === 'string') errorMsg = errorDetail;
      else if (errorDetail && typeof errorDetail === 'object') {
        errorMsg = Object.entries(errorDetail)
          .map(([key, value]) => `${key.replace(/_/g, " ")}: ${Array.isArray(value) ? value.join(", ") : String(value)}`)
          .join("; ");
      }
      toast.error(errorMsg || "Upload failed due to an unknown error.");
      console.error('Error uploading file:', error.response || error);
    } finally {
      setIsUploading(false);
    }
  };

  const handleManualSync = async (assetId) => {
    toast.promise(
        // Use correct endpoint, apiClient adds auth headers
        apiClient.post(`/crm-api/media/media-assets/${assetId}/sync_with_meta/`, {}), // Ensure backend URL matches this
        {
            loading: 'Initiating sync with Meta...',
            success: (response) => {
                setRefreshKey(prev => prev + 1);
                return response.data?.message || 'Sync initiated successfully! Status will update shortly.';
            },
            error: (err) => err.response?.data?.detail || err.message || 'Failed to trigger sync.',
        }
    );
  };

  const handleDelete = async (assetId) => {
    if (!window.confirm("Are you sure you want to delete this asset? This action cannot be undone.")) {
        return;
    }
    toast.promise(
        // Use correct endpoint, apiClient adds auth headers
        apiClient.delete(`/crm-api/media/media-assets/${assetId}/`),
        {
            loading: 'Deleting asset...',
            success: () => {
                setRefreshKey(prev => prev + 1);
                return 'Asset deleted successfully.';
            },
            error: (err) => err.response?.data?.detail || err.message || 'Failed to delete asset.',
        }
    );
  };
  
  // Initial loading state for the whole page if auth is still loading
  if (auth && auth.isLoadingAuth) {
    return (
        <div className="flex items-center justify-center min-h-[calc(100vh-10rem)]">
          <FiLoader className="h-12 w-12 animate-spin text-blue-500" />
          <p className="ml-4 text-lg">Loading Authentication...</p>
        </div>
    );
  }


  const filteredAssets = Array.isArray(assets) ? assets.filter(asset => {
    const typeMatch = filterType === 'all' || asset.asset_type === filterType; // Match asset.asset_type
    const statusMatch = filterStatus === 'all' || asset.status === filterStatus;
    return typeMatch && statusMatch;
  }) : [];

  return (
    <div className="container mx-auto py-6 px-4 sm:px-6 lg:px-8">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <motion.div initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.5 }}>
          <Card className="lg:col-span-1 shadow-lg dark:bg-slate-800">
            <CardHeader>
              <CardTitle className="text-xl font-semibold dark:text-slate-100">Upload New Media</CardTitle>
              <CardDescription className="dark:text-slate-400">Add new assets to your library.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="file-upload" className="dark:text-slate-300">Select File</Label>
                <Input id="file-upload" type="file" onChange={handleFileChange} disabled={isUploading} ref={fileInputRef} 
                       className="dark:bg-slate-700 dark:border-slate-600 file:text-primary file:font-semibold file:bg-primary-foreground hover:file:bg-primary-foreground/90"/>
                {selectedFile && (
                  <div className="text-xs text-gray-600 dark:text-gray-400 pt-1">
                    {selectedFile.name} ({formatBytes(selectedFile.size)})
                  </div>
                )}
              </div>
              <div className="space-y-2">
                <Label htmlFor="assetName" className="dark:text-slate-300">Asset Name</Label> {/* Changed htmlFor to assetName */}
                <Input id="assetName" type="text" value={assetName} onChange={(e) => setAssetName(e.target.value)} placeholder="e.g., Welcome Video" required disabled={isUploading} className="dark:bg-slate-700 dark:border-slate-600" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="assetType" className="dark:text-slate-300">Asset Type</Label> {/* Changed htmlFor to assetType */}
                <Select value={assetType} onValueChange={setAssetType} disabled={isUploading}>
                  <SelectTrigger className="dark:bg-slate-700 dark:border-slate-600"><SelectValue placeholder="Select media type" /></SelectTrigger>
                  <SelectContent className="dark:bg-slate-700">
                    {ASSET_TYPE_CHOICES.map(choice => (
                        <SelectItem key={choice.value} value={choice.value}>{choice.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="assetNotes" className="dark:text-slate-300">Notes/Description (Optional)</Label> {/* Changed htmlFor and state variable */}
                <Input id="assetNotes" type="text" value={assetNotes} onChange={(e) => setAssetNotes(e.target.value)} placeholder="Brief description or notes" disabled={isUploading} className="dark:bg-slate-700 dark:border-slate-600" />
              </div>
            </CardContent>
            <CardFooter>
              <Button onClick={handleUpload} disabled={!selectedFile || !assetName.trim() || isUploading} className="w-full bg-green-600 hover:bg-green-700">
                {isUploading ? <FiLoader className="mr-2 h-4 w-4 animate-spin" /> : <FiUploadCloud className="mr-2 h-4 w-4" />}
                {isUploading ? 'Uploading...' : 'Upload Asset'}
              </Button>
            </CardFooter>
          </Card>
        </motion.div>

        <motion.div 
            className="lg:col-span-2 space-y-6"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.5, delay: 0.1 }}
        >
          <Card className="shadow-lg dark:bg-slate-800">
            <CardHeader>
              <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                <div className="flex-1">
                    <CardTitle className="text-xl font-semibold dark:text-slate-100">Existing Media Assets</CardTitle>
                    <CardDescription className="dark:text-slate-400">View, sync, or delete your assets.</CardDescription>
                </div>
                <div className="flex gap-2 flex-wrap">
                  <Select value={filterType} onValueChange={setFilterType}>
                    <SelectTrigger className="w-full sm:w-[130px] dark:bg-slate-700 dark:border-slate-600"><SelectValue placeholder="All Types" /></SelectTrigger>
                    <SelectContent className="dark:bg-slate-700">
                      <SelectItem value="all">All Types</SelectItem>
                      {ASSET_TYPE_CHOICES.map(choice => (
                        <SelectItem key={choice.value} value={choice.value}>{choice.label}s</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Select value={filterStatus} onValueChange={setFilterStatus}>
                    <SelectTrigger className="w-full sm:w-[140px] dark:bg-slate-700 dark:border-slate-600"><SelectValue placeholder="All Statuses" /></SelectTrigger>
                    <SelectContent className="dark:bg-slate-700">
                      <SelectItem value="all">All Statuses</SelectItem>
                      {/* Values should match backend status choices exactly */}
                      <SelectItem value="LOCAL">Local</SelectItem>
                      <SelectItem value="PENDING">Pending</SelectItem>
                      <SelectItem value="SYNCED">Synced</SelectItem>
                      <SelectItem value="ERROR_UPLOAD">Upload Error</SelectItem>
                      <SelectItem value="ERROR_RESYNC">Resync Error</SelectItem>
                      <SelectItem value="EXPIRED">Expired</SelectItem>
                      <SelectItem value="DELETED">Deleted</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button variant="outline" onClick={() => setRefreshKey(prev => prev + 1)} disabled={isLoading} className="dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700">
                    <FiRefreshCw className={`h-4 w-4 ${isLoading && assets.length > 0 ? 'animate-spin' : ''} sm:mr-2`} /> {/* Spin only when refreshing table */}
                    <span className="hidden sm:inline">Refresh</span>
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {isLoading && assets.length === 0 ? ( // Only show big loader if initial load and no assets
                <div className="flex justify-center items-center h-32">
                  <FiLoader className="h-8 w-8 animate-spin text-blue-500" />
                </div>
              ) : filteredAssets.length === 0 ? (
                <div className="text-center py-10 text-gray-500 dark:text-gray-400">
                  <FiImage className="h-16 w-16 text-gray-400 dark:text-gray-500 mx-auto mb-4" />
                  No media assets found matching your criteria.
                </div>
              ) : (
                <ScrollArea className="h-[calc(100vh-26rem)] border dark:border-slate-700 rounded-md"> {/* Adjusted height example */}
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-12"></TableHead>
                        <TableHead>Name & Notes</TableHead>
                        <TableHead>Type</TableHead>
                        <TableHead>Size</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Uploaded</TableHead>
                        <TableHead className="text-right pr-2">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filteredAssets.map((asset) => (
                        <MediaAssetRowDisplay key={asset.id} asset={asset} onSync={handleManualSync} onDelete={handleDelete} />
                      ))}
                    </TableBody>
                  </Table>
                </ScrollArea>
              )}
            </CardContent>
          </Card>
        </motion.div>
      </div>
    </div>
  );
}