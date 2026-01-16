/**
 * Supabase Client Configuration
 * =============================
 * 
 * This sets up the Supabase client for authentication.
 * Make sure to add your Supabase URL and anon key to .env
 */

import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || '';
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || '';

// Debug: log what we got (remove in production)
console.log('Supabase URL:', supabaseUrl ? 'SET' : 'MISSING');
console.log('Supabase Key:', supabaseAnonKey ? 'SET' : 'MISSING');

if (!supabaseUrl || !supabaseAnonKey) {
  console.error('Missing Supabase environment variables! Check your .env file.');
}

// Create client (will work but auth won't function if vars are missing)
export const supabase = createClient(
  supabaseUrl || 'https://placeholder.supabase.co', 
  supabaseAnonKey || 'placeholder-key'
);

/**
 * Sign in with Google OAuth
 * This will redirect to Google login and return with tokens
 */
export async function signInWithGoogle() {
  const { data, error } = await supabase.auth.signInWithOAuth({
    provider: 'google',
    options: {
      scopes: 'email https://www.googleapis.com/auth/gmail.readonly',
      redirectTo: window.location.origin,
    },
  });
  
  if (error) throw error;
  return data;
}

/**
 * Sign out the current user
 */
export async function signOut() {
  const { error } = await supabase.auth.signOut();
  if (error) throw error;
}

/**
 * Get the current session
 */
export async function getSession() {
  const { data: { session }, error } = await supabase.auth.getSession();
  if (error) throw error;
  return session;
}

/**
 * Get the Google provider token (for Gmail API)
 */
export async function getProviderToken() {
  const session = await getSession();
  return session?.provider_token || null;
}

/**
 * Subscribe to auth state changes
 */
export function onAuthStateChange(callback) {
  return supabase.auth.onAuthStateChange(callback);
}
