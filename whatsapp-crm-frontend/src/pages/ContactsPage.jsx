// src/pages/MediaLibraryPage.jsx
import React from 'react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { FiImage } from 'react-icons/fi';


export default function MediaLibraryPage() {
  return (
    <div className="container mx-auto p-4 md:p-6 lg:p-8">
      <Card className="dark:bg-slate-800 dark:border-slate-700">
        <CardHeader>
          <CardTitle className="text-2xl font-semibold dark:text-slate-50 flex items-center">
            <FiImage className="mr-3 h-6 w-6 text-blue-500" /> Media Library
          </CardTitle>
          <CardDescription className="dark:text-slate-400">
            Manage your uploaded media assets (images, videos, documents).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="dark:text-slate-300">Media asset management interface will be here.</p>
          <p className="dark:text-slate-400 text-sm mt-2">
            This section will allow you to upload new media, view existing media,
            sync with WhatsApp, and delete assets. It will use the
            <code>/api/v1/media/media-assets/</code> API endpoint.
          </p>
          {/* TODO: Implement MediaAsset listing, upload, sync, delete UI */}
        </CardContent>
      </Card>
    </div>
  );
}