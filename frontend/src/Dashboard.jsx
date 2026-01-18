/**
 * Dashboard Component
 * ===================
 * 
 * The main dashboard view shown after user logs in.
 * Displays fetched emails and saved job applications.
 * 
 * This component is lazy-loaded to improve initial page load time.
 */

import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { 
  Mail, 
  Zap,
  Loader2,
  RefreshCw,
  CheckCircle,
  AlertCircle,
  Calendar,
  Building,
  Briefcase
} from 'lucide-react';
import { fetchEmails, saveApplication, getApplications, processLatestEmail } from './lib/api';


const Dashboard = ({ user, providerToken }) => {
  const [emails, setEmails] = useState([]);
  const [applications, setApplications] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [processingId, setProcessingId] = useState(null);

  // Fetch applications on mount
  useEffect(() => {
    loadApplications();
  }, []);

  const loadApplications = async () => {
    try {
      const apps = await getApplications();
      setApplications(apps);
    } catch (err) {
      console.error('Failed to load applications:', err);
    }
  };

  const handleFetchEmails = async () => {
    if (!providerToken) {
      setError('No Gmail token available. Please sign in again.');
      return;
    }
    
    setLoading(true);
    setError(null);
    try {
      // API returns array directly, not {emails: [...]}
      const result = await fetchEmails(providerToken, 'in:inbox', 10);
      setEmails(result || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleProcessLatest = async () => {
    if (!providerToken) {
      setError('No Gmail token available. Please sign in again.');
      return;
    }
    
    setLoading(true);
    setError(null);
    try {
      await processLatestEmail(providerToken);
      await loadApplications();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSaveEmail = async (emailId) => {
    if (!providerToken) return;
    
    setProcessingId(emailId);
    try {
      await saveApplication(providerToken, emailId);
      await loadApplications();
    } catch (err) {
      setError(err.message);
    } finally {
      setProcessingId(null);
    }
  };

  return (
    <div className="min-h-screen pt-24 px-6 pb-12">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="mb-12">
          <h1 className="text-4xl font-black text-white mb-2 uppercase tracking-tight">
            Welcome, {user?.email?.split('@')[0]}
          </h1>
          <p className="text-gray-400">Manage your job applications</p>
        </div>

        {/* Error display */}
        {error && (
          <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 rounded-2xl flex items-center gap-3 text-red-400">
            <AlertCircle className="w-5 h-5" />
            {error}
          </div>
        )}

        {/* Action buttons */}
        <div className="flex flex-wrap gap-4 mb-12">
          <button
            onClick={handleFetchEmails}
            disabled={loading}
            className="flex items-center gap-2 bg-indigo-600 px-6 py-3 rounded-full text-white font-bold uppercase text-sm hover:bg-indigo-500 transition-colors disabled:opacity-50"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Mail className="w-4 h-4" />}
            Fetch Emails
          </button>
          
          <button
            onClick={handleProcessLatest}
            disabled={loading}
            className="flex items-center gap-2 bg-white/10 border border-white/20 px-6 py-3 rounded-full text-white font-bold uppercase text-sm hover:bg-white/20 transition-colors disabled:opacity-50"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
            Process Latest
          </button>

          <button
            onClick={loadApplications}
            className="flex items-center gap-2 bg-white/5 border border-white/10 px-6 py-3 rounded-full text-gray-400 font-bold uppercase text-sm hover:text-white hover:border-white/20 transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
        </div>

        {/* Two column layout */}
        <div className="grid lg:grid-cols-2 gap-8">
          {/* Emails section */}
          <div>
            <h2 className="text-xl font-black text-white mb-4 uppercase flex items-center gap-2">
              <Mail className="w-5 h-5 text-indigo-400" />
              Recent Emails
            </h2>
            
            {emails.length === 0 ? (
              <div className="bg-white/5 border border-white/10 rounded-3xl p-8 text-center">
                <Mail className="w-12 h-12 text-gray-600 mx-auto mb-4" />
                <p className="text-gray-500">Click "Fetch Emails" to load your inbox</p>
              </div>
            ) : (
              <div className="space-y-3">
                {emails.map((email) => (
                  <motion.div
                    key={email.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="bg-white/5 border border-white/10 rounded-2xl p-4 hover:bg-white/10 transition-colors"
                  >
                    <div className="flex justify-between items-start gap-4">
                      <div className="flex-1 min-w-0">
                        <h3 className="font-bold text-white truncate">{email.subject || 'No Subject'}</h3>
                        <p className="text-sm text-gray-400 truncate">{email.sender}</p>
                        <p className="text-xs text-gray-600 mt-1">{email.date}</p>
                      </div>
                      <button
                        onClick={() => handleSaveEmail(email.id)}
                        disabled={processingId === email.id}
                        className="flex-shrink-0 bg-indigo-600 p-2 rounded-full hover:bg-indigo-500 transition-colors disabled:opacity-50"
                      >
                        {processingId === email.id ? (
                          <Loader2 className="w-4 h-4 text-white animate-spin" />
                        ) : (
                          <CheckCircle className="w-4 h-4 text-white" />
                        )}
                      </button>
                    </div>
                  </motion.div>
                ))}
              </div>
            )}
          </div>

          {/* Applications section */}
          <div>
            <h2 className="text-xl font-black text-white mb-4 uppercase flex items-center gap-2">
              <Briefcase className="w-5 h-5 text-indigo-400" />
              Saved Applications ({applications.length})
            </h2>
            
            {applications.length === 0 ? (
              <div className="bg-white/5 border border-white/10 rounded-3xl p-8 text-center">
                <Briefcase className="w-12 h-12 text-gray-600 mx-auto mb-4" />
                <p className="text-gray-500">No applications saved yet</p>
              </div>
            ) : (
              <div className="space-y-3">
                {applications.map((app, index) => (
                  <motion.div
                    key={app.id || index}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: index * 0.05 }}
                    className="bg-white/5 border border-white/10 rounded-2xl p-4 hover:bg-white/10 transition-colors"
                  >
                    <div className="flex items-start gap-3">
                      <div className="w-10 h-10 bg-indigo-600/20 rounded-xl flex items-center justify-center flex-shrink-0">
                        <Building className="w-5 h-5 text-indigo-400" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="font-bold text-white">{app.company_name || 'Unknown Company'}</h3>
                        <p className="text-sm text-indigo-400">{app.job_title || 'Job Application'}</p>
                        <div className="flex items-center gap-3 mt-2 text-xs text-gray-500">
                          <span className="flex items-center gap-1">
                            <Calendar className="w-3 h-3" />
                            {app.applied_date || 'Recently'}
                          </span>
                          <span className={`px-2 py-0.5 rounded-full ${
                            app.status === 'applied' ? 'bg-blue-500/20 text-blue-400' :
                            app.status === 'interview' ? 'bg-green-500/20 text-green-400' :
                            app.status === 'rejected' ? 'bg-red-500/20 text-red-400' :
                            'bg-gray-500/20 text-gray-400'
                          }`}>
                            {app.status || 'pending'}
                          </span>
                        </div>
                      </div>
                    </div>
                  </motion.div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
