export interface MemoryRow {id:string;value:string;kind:string;duplicate:boolean;origin:string}
export interface MemoryPreview {preview_id:string;rows:MemoryRow[];blocked:number;skipped:number;note:string}
export interface NativeWindow {id:string;pid:number;title:string;app:string;minimized:boolean}
export interface DesktopGrant {request_id:string;action:'capture'|'activate'|'launch';target:{title:string;app?:string;path?:string};expires_in:number}
export interface SourceExcerpt {path:string;start:number;end:number;total_lines:number;content:string;sha256:string;read_only:boolean;truncated:boolean}
export interface SourceIndex {files:{path:string;bytes:number}[];access:string}
export interface SelfWorkspace {project:string;files:number;commit:string;workflow:string;live_install_modified:boolean}
export interface ExtensionHooks {
 api<T=any>(path:string,body?:unknown,method?:string):Promise<T>;
 notify(text:string,error?:boolean):void;
 vision(image:string,question:string):void;
 source(excerpt:SourceExcerpt,question:string):void;
 project(project:string,task:string):void;
}
